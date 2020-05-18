import os
import datetime as dt
import re

from flask import Flask
from flask_ask import Ask, statement, question, session, convert_errors, context
from pytz import timezone

try:
    import requests
except ModuleNotFoundError:
    from botocore.vendored import requests

from octopus.octopus import OctopusEnergy, APIError, RequestedSlotTooLongError

# Debug information logged if noisy == True
if os.environ['NOISY'] == 'True':
    noisy = True
else:
    noisy = False

if noisy:
    print("Loading lambda_function.py module")

# Exception for when permission has not been granted to retrieve the device postcode
# from Amazon
class PostcodeNoAuthorisation(Exception):
    pass

# Exception for when countryCode is outside of the UK
class OutOfGeographicalScope(Exception):
    pass

# Exception for when postcode doesn't match regex.
class InvalidPostcode(Exception):
    pass


app = Flask(__name__)
ask = Ask(app, "/")

# Postcode regex matcher.
def check_postcode(postcode):
    # Regex from https://stackoverflow.com/questions/164979/regex-for-matching-uk-postcodes
    pcregex = re.compile(r'^\s*([A-Z][A-HJ-Y]?[0-9][A-Z0-9]?\s?[0-9][A-Z]{2}|GIR ?0A{2})\s*$')

    if pcregex.match(postcode.upper()):
        if noisy:
            print("Debug: postcode matched UK postcode regex")
    else:
        print("Error: not a matching UK postcode: {}".format(postcode))
        return False

    return True

# Retrieve the cheapest slot
def get_timeframe(o, numberOfSlots):

    uktz = timezone('Europe/London') # This skill is only meaningful in the UK

    slotStart, slotFinish = o.getCheapestSlot(numberOfSlots * 30) # it takes minutes as arg

    # The times from the Octopus API are in UTC, so need converting if we're in summer
    # time at the moment.
    slotStart = slotStart.astimezone(uktz)
    slotFinish = slotFinish.astimezone(uktz)

    return slotStart, slotFinish

def get_postcode(deviceId, apiEndpoint, apiAccessToken):

    requestURL = "{}/v1/devices/{}/settings/address/countryAndPostalCode".format(apiEndpoint, deviceId)

    requestHeader = {
        'Accept': 'application/json',
        'Authorization': 'Bearer {}'.format(apiAccessToken)
    }

    r = requests.get(requestURL, headers=requestHeader)

    if r.status_code == 403:
        raise PostcodeNoAuthorisation

    if r.status_code == 200:
        if r.json()['countryCode'] == 'GB':
            postcode = r.json()['postalCode']
        else:
            # The skill is only published to UK, but this added in response to Amazon review
            raise OutOfGeographicalScope

    if r.status_code in [204, 404, 405, 429, 500]:
        print("Error: Unsupported error calling postcode retrieval API, status: {}".format(r.status_code))
        raise APIError

    if check_postcode(postcode) != True: # this tests against a postcode matching regex...
        raise InvalidPostcode

    return postcode


# Convert a number of slots to an English description of their duration.
# It's used so: The cheapest $RETURN_FROM_THIS_FUNCTION slot runs from ...
def slotLengthWords(numberOfSlots):

    numberOfSlots = int(numberOfSlots)
    # In minutes up to 90 minutes.
    if numberOfSlots < 4:
        result = str(numberOfSlots*30) + ' minute'
    else: # In hours, including halves if longer than 90 minutes.
        result = str(numberOfSlots // 2)
        if numberOfSlots % 2 == 1:
            result = result + ' and a half'

        result = result + ' hour'

    return result


@ask.launch
def start_skill():
    if noisy:
        print('Debug: start_skill() entered')

    welcome_message = 'Hello there, I can tell you the cheapest time to do something that \
        uses a lot of electricity on your Agile Octopus tariff. How long a time slot do \
        you need?'

    return question(welcome_message)


@ask.intent("FindCheapestSlot", convert={'Length': 'timedelta'})
def find_cheapest_slot(Length):

    if noisy:
        print('Debug: find_cheapest_slot() entered - {}'.format(Length))

    # Are we allowed to access the user's postcode?
    try:
        postcode = get_postcode(context.System.device.deviceId, context.System.apiEndpoint, context.System.apiAccessToken)
    except PostcodeNoAuthorisation:
        if noisy:
            print("Debug: No postcode permissions, so requesting access to country_and_postal_code")
        return statement("Please can you visit the Alexa app and authorise me to access \
            your postcode, so that I can look up which electricity region you are in.")\
            .consent_card("read::alexa:device:all:address:country_and_postal_code")
    except OutOfGeographicalScope:
        print("Error: Run from outside of the UK, so no valid postcode possible")
        return statement("I'm really sorry, but I can only help you if you're in the \
            United Kingdom. If you actually *are* in the UK, please check the address in \
            your device settings in the Alexa app.")
    except InvalidPostcode:
        print("Error: doesn't look like a valid postcode")
        return statement("I'm very sorry, but I don't recognise your postcode. To fix \
            this, you might try checking the address in your device settings in the \
            Alexa app.")
    except Exception as e:
        print("Error: unexpected error getting postcode from Amazon - {}".format(e))
        return statement("I'm so sorry, but I can't help - for some reason I can't \
            retrieve your device's postcode.")

    # Recover gracefully if we didn't catch the slot length - probably won't happen
    # as we have elicitation on for the Length slot.
    if 'Length' in convert_errors:
        return question("Sorry, could you repeat the length of your required time slot?")

    try:
        o = OctopusEnergy(postcode, noisy=noisy)
    except ValueError:
        print("Error: Postcode lookup failed for {}, recommending checking the Alexa app config".format(postcode))
        return statement("I'm so sorry, but I could not look up your postcode sector, \
            so I don't know which electricity region you are in. \
            Could you check the address in your device settings in the Alexa app?")
    except Exception as e:
        print("Error: can't instantiate OctopusEnergy class for that postcode - {}".format(e))
        return statement("I'm sorry, but my connection to Octopus Energy appears \
            to have gone a bit pear shaped, so I can't help you at the moment. \
            Feel free to try again in a moment?")

    durationInSlots = Length.total_seconds() // 1800

    # Less than half an hour is rounded up to half an hour.
    if durationInSlots == 0:
        durationInSlots = 1

    # Retrieve the cheapest slot
    try:
        slotStart, slotFinish = get_timeframe(o, durationInSlots)
    except RequestedSlotTooLongError:
        return statement("I'm sorry, I can't find you a {} slot - it's too long".format(
            slotLengthWords(durationInSlots)))
    except:
        print("Error: OctopusEnergy threw an exception getting time slots, blaming connectivity")
        return statement("I'm sorry, but my connection to Octopus Energy appears \
            to have gone a bit pear shaped, so I can't help you at the moment. \
            Feel free to try again in a moment?")

    # otherwise...
    result = 'The cheapest {} slot runs from {} to {}'.format(
        slotLengthWords(durationInSlots),
        slotStart.strftime('%I:%M%p'), slotFinish.strftime('%I:%M%p'))

    print("Tariff: {}, Returned: {}".format(o.octopusGetTariffCode(), result))

    return statement(result)

# Manage Amazon's default intents...
@ask.intent("AMAZON.CancelIntent")
@ask.intent("AMAZON.StopIntent")
def abandon_intent():
    return statement("Ok, bye for now!")

@ask.intent("AMAZON.NavigateHomeIntent")
@ask.intent("AMAZON.FallbackIntent")
@ask.intent("AMAZON.HelpIntent")
def help_intent():
    return question("I can tell you the cheapest time to do something that \
        uses a lot of energy on your Agile Octopus electricity tariff. How long \
        will your high energy consumption run for?")

if noisy:
    print("Debug: Loaded lambda_function.py module")

def lambda_handler(event, _context):
    return ask.run_aws_lambda(event)

if __name__ == '__main__':
    app.run()
