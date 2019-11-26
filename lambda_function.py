import os
import datetime as dt

from flask import Flask
from flask_ask import Ask, statement, question, session, convert_errors
from pytz import timezone

from octopus.octopus import OctopusEnergy

# Debug information logged if noisy == True
noisy = True

if noisy:
	print("Loading lambda_function.py module")

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

def get_postcode():
	postCode = os.environ['MY_POSTCODE'] # need to replace this with Alexa user postcode lookup
	
	if postCode == '':
		print("No postcode available, using the postcode for Ilkley Post Office")
		postCode = 'LS29 8HF'
	
	return postCode

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
		uses a lot of electricity. How long a time slot do you need?'
		
	return question(welcome_message)


@ask.intent("FindCheapestSlot", convert={'Length': 'timedelta'})
def find_cheapest_slot(Length):

	if noisy:
		print('find_cheapest_slot() entered - {}'.format(Length))
	
	# Recover gracefully if we didn't catch the slot length
	if 'Length' in convert_errors:
		return question("Sorry, could you repeat the length of your required time slot?")

	o = OctopusEnergy(get_postcode())

	durationInSlots = Length.total_seconds() // 1800
	
	# Less than half an hour is rounded up to half an hour.
	if durationInSlots == 0:
		durationInSlots = 1 

	slotStart, slotFinish = get_timeframe(o, durationInSlots)
	
	# If no slot of that length is available because it's too long...
	if slotStart == None:
		return statement("I'm sorry, I can't find you a {} slot - it's too long".format(
			slotLengthWords(durationInSlots)))
	
	result = 'The cheapest {} slot runs from {} to {}'.format(
			slotLengthWords(durationInSlots),
			slotStart.strftime('%I:%M%p'), slotFinish.strftime('%I:%M%p'))
	
	return statement(result)



if noisy:
	print("Loaded lambda_function.py module")

def lambda_handler(event, _context):
	return ask.run_aws_lambda(event)

if __name__ == '__main__':
	app.run()

