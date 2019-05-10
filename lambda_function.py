import os
import datetime as dt

from flask import Flask
from flask_ask import Ask, statement, question, session
from pytz import timezone

from octopus.octopus import OctopusEnergy

print("Loading lambda_function.py module")

# This file has data mapping postcodes to electricity regions. I hacked it together
# from various publically available sources. It's not proven to be complete.
postCodeLookupFile = 'PC2ED.csv'

app = Flask(__name__)
ask = Ask(app, "/")

# 
def get_timeframe(o, numberOfSlots):

	uktz = timezone('Europe/London')

	start, finish = o.getCheapestSlot(numberOfSlots * 30) # it takes minutes as arg
	
	# The times from the Octopus API are in UTC, so need converting if we're in summer
	# time at the moment.		
	start = start.astimezone(uktz)
	finish = finish.astimezone(uktz)
	
	return start, finish

def get_postcode():
	postCode = os.environ['MY_POSTCODE'] # need to replace this with Alexa user postcode lookup
	
	if postCode == '':
		print("No MY_POSTCODE environment variable found, returning the postcode for Ilkley Post Office")
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
	print('start_skill() entered')
	welcome_message = 'Hello there, how long do you need your high power for?'
	return question(welcome_message)


@ask.intent("FindCheapestSlot", convert={'Length': 'timedelta'})
def find_cheapest_slot(Length):

	print('find_cheapest_slot() entered - {}'.format(Length))

	o = OctopusEnergy(get_postcode())

	durationInSlots = Length.total_seconds() // 1800

	start, finish = get_timeframe(o, durationInSlots)
	
	result = 'The cheapest {} slot runs from {} to {}'.format(
			slotLengthWords(durationInSlots),
			start.strftime('%I:%M%p'), finish.strftime('%I:%M%p'))
	
	return statement(result)



print("Loaded lambda_function.py module")

def lambda_handler(event, _context):
	return ask.run_aws_lambda(event)

if __name__ == '__main__':
	app.run()

