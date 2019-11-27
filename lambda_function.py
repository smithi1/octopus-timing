import os
import datetime as dt

from flask import Flask
from flask_ask import Ask, statement, question, session, convert_errors, context
from pytz import timezone

try:
    import requests
except ModuleNotFoundError:
    from botocore.vendored import requests

from octopus.octopus import OctopusEnergy, APIError

# Debug information logged if noisy == True
noisy = False

if noisy:
    print("Loading lambda_function.py module")
    
# Exception for when permission has not been granted to retrieve the device postcode
# from Amazon
class PostcodeNoAuthorisation(Exception):
    pass


# This file has data mapping postcodes to electricity regions. I hacked it together
# from various publically available sources. It's not proven to be complete.
postCodeLookupFile = 'PC2ED.csv'

app = Flask(__name__)
ask = Ask(app, "/")

def get_timeframe(o, numberOfSlots):

    uktz = timezone('Europe/London') # This skill is only meaningful in the UK

    slotStart, slotFinish = o.getCheapestSlot(numberOfSlots * 30) # it takes minutes as arg
    
    if slotStart == None:
        return None, None # the requested slot was too long for the data.
    
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
        postcode = r.json()['postalCode']
            
    if r.status_code in [204, 404, 405, 429, 500]:
        print("Unsupported error calling postcode retrieval API, status: {}".format(r.status_code))
        raise APIError
    
    if postcode == '': # this should probably test against a postcode matching regex...
        print("No postcode retrieved")
        raise APIError
    
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
        print('start_skill() entered')
        
    welcome_message = 'Hello there, I can tell you the cheapest time to do something that \
        uses a lot of electricity on your Agile Octopus tariff. How long a time slot do \
        you need?'
        
    return question(welcome_message)


@ask.intent("FindCheapestSlot", convert={'Length': 'timedelta'})
def find_cheapest_slot(Length):

    if noisy:
        print('find_cheapest_slot() entered - {}'.format(Length))

    # Are we allowed to access the user's postcode?
    try:
        postcode = get_postcode(context.System.device.deviceId, context.System.apiEndpoint, context.System.apiAccessToken)
    except PostcodeNoAuthorisation:
        print("No postcode permissions, so requesting access to country_and_postal_code")
        return statement("Please can you visit the Alexa app to authorise me to access \
            your postcode, so that I can look up which electricity region you are in")\
            .consent_card("read::alexa:device:all:address:country_and_postal_code")
    except APIError:
        print("API Error, so no postcode available")
        return statement("I'm so sorry, but I can't help - for some reason I can't retrieve your device's postcode.")
    
    # Recover gracefully if we didn't catch the slot length
    if 'Length' in convert_errors:
        return question("Sorry, could you repeat the length of your required time slot?")

    o = OctopusEnergy(postcode)

    durationInSlots = Length.total_seconds() // 1800
    
    # Less than half an hour is rounded up to half an hour.
    if durationInSlots == 0:
        durationInSlots = 1

    slotStart, slotFinish = get_timeframe(o, durationInSlots)
    
    # If no slot of that length is available because it's too long...
    if slotStart == None:
        return statement("I'm sorry, I can't find you a {} slot - it's too long".format(
            slotLengthWords(durationInSlots)))
    
    # otherwise...
    result = 'The cheapest {} slot runs from {} to {}'.format(
            slotLengthWords(durationInSlots),
            slotStart.strftime('%I:%M%p'), slotFinish.strftime('%I:%M%p'))
    
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
    print("Loaded lambda_function.py module")

def lambda_handler(event, _context):
    return ask.run_aws_lambda(event)

if __name__ == '__main__':
    app.run()