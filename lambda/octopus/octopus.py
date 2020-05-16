import numpy as np
import pandas as pd
import re

try:
	import requests
except ModuleNotFoundError:
	from botocore.vendored import requests
	
import json
import time
import datetime as dt

from pytz import timezone

class APIError(Exception):
	pass
	
class RequestedSlotTooLongError(Exception):
	pass

class OctopusEnergy:

	octopusAPIVersion = '1'
	baseURL = 'https://api.octopus.energy/v' + octopusAPIVersion + '/'
	
	productCode = None
	tariffCode = None
	tariffCosts = pd.DataFrame() # empty dataframe


	def __init__(self, postcode=None, distributorCode=None, noisy=False):
	
		if all(v is None for v in {postcode, distributorCode}):
			raise ValueError('Expected either postcode or distributorCode')
	
		self.noisy = noisy
		self.productCode = None # Octopus Energy product code for Agile Octopus
		self.tariffCode = None # Octopus Energy tariff code for user, derived from their postcode
				
		# Handle distributorCode
		if distributorCode == None:
			self.distributorCode = None
		else: 

			# Check it's a distributor code that we know about.
			if distributorCode not in ['_P', '_N', '_G', '_F', '_M', '_D', '_B', '_E', '_K', '_C', '_A', '_L', '_H', '_J']:
				raise ValueError('"' + distributorCode + '" is not a known distributorCode')
				
			# Remember it	
			self.distributorCode = distributorCode
			
			# Ignore any postcode that has been supplied, it's redundant.
			postcode = None
			
			if self.noisy:
				print('Debug: OctopusEnergy: Known distributorCode supplied as {}, ignoring any supplied postcode'.format(distributorCode))
	
		# Handle postcode
		if postcode == None:
			self.postcode = None
		else:
			if self.noisy:
				print('Debug: OctopusEnergy: Postcode supplied as {}'.format(postcode))
				
			nonAlphaRE = re.compile('[^A-Z0-9]+')

			self.postcode = nonAlphaRE.sub('', str(postcode).upper())[:-3]
			
			try:
				self.distributorCode = self.octopusGetDistributorCode(self.postcode)
			except APIError as e:
				print("Debug: OctopusEnergy: Error calling Octopus Energy API to get distributor code - {}".format(string(e)))
				raise
			except PostcodeError as e:
				print("Debug: OctopusEnergy: Error in postcode - {}".format(string(e)))
			
			if self.noisy:
				print('Debug: OctopusEnergy: Postcode supplied as {}, distributor code looked up as {}'.format(self.postcode, self.distributorCode))

	# Returns the time in the format required by the API, times not on the hour or
	# half hour are rounded to the next one.		
	def apiTimeFormat(t):
	
		if t.minute != 0 and t.minute != 30:
			if t.minute < 30:
				t = dt.datetime(t.year, t.month, t.day, t.hour, 30, 0)
			else:
				t = t + dt.timedelta(hours=1)
				t = dt.datetime(t.year, t.month, t.day, t.hour, 0, 0)
			
		return t.strftime('%Y-%m-%dT%H:%M')
	
	# Return time period parameters for the API going from now until tomorrow night.
	# Return format is params which can be plugged into API call
	def nowUntilTomorrow(self):
		
		t = dt.datetime.now(timezone('Europe/London'))
		tm = t + dt.timedelta(1)
		tm = dt.datetime(tm.year, tm.month, tm.day, 23, 30, 0)

		today = OctopusEnergy.apiTimeFormat(t)
		tomorrow = OctopusEnergy.apiTimeFormat(tm)
		
		return {
			'period_from': today, 'period_to': tomorrow
		}

	# Look up the postcode via the API. Replaces the former lookup file.
	def octopusGetDistributorCode(self, postcode):
		
		url = self.baseURL + 'industry/grid-supply-points/'
		
		if self.noisy:
				print("Debug: OctopusEnergy: attempting to get distributor code from postcode: {}".format(postcode))

		try:
			resp = requests.get(url, params={'postcode': postcode})
		except requests.exceptions.RequestException as e:
			print("Error: couldn't retrieve distributor code for postcode=|{}| ".format(postcode))
			raise APIError(string(e))
			
		try:
			results = resp.json()['results']
		except KeyError:
			print('Error: OctopusEnergy: No "results" in API response')
			raise
		
		# No results, perhaps a non-existant postcode
		if len(results) == 0:
			print("Error: OctopusEnergy: Could not find a distributor code for postcode=|{}|".format(postcode))
			raise PostcodeError("No distributor code found for postcode")
			
		# too many results - perhaps the postcode was just an area code - LS vs LS29 for example
		# Apparently, there's a London postcode area with two electricity regions in it, which we just can't handle at the moment.
		if len(results) > 1:
			print("Error: OctopusEnergy: {} distributor codes returned for postcode=|{}|".format(len(results), postcode))
			raise PostcodeError("Postcode too ambiguous")

		try:
			distCode = results[0]['group_id']
		except IndexError as e:
			print(e)
			raise
		
		if self.noisy:
			print("Debug: OctopusEnergy: Distributor code returned: " + distCode)
		
		return distCode

	
	# Get the "agile" product code. Currently there's only one, but this will need to 
	# be revisited if more appear, so as to figure out which one to use. Currently 
	# the first one returned is used.
	
	# Update 11th June: The is_tracker flag has been unset for Agile Octopus, and there's
	# now no way to just get Agile tariffs. Incidentally, there's also a new Agile
	# tariff for sending electricity to the grid.
	def octopusGetProductCode(self):
	
		if self.productCode == None:
	
			url = self.baseURL + 'products/'
		
			if self.noisy:
				print('Debug: OctopusEnergy: attempting to get product code from API')
				
			try:
				resp = requests.get(url)
			except requests.exceptions.RequestException as e:
				print('Error: OctopusEnergy: Product code retrieve from Octopus API failed: {}'.format(str(e)))
				raise
		
			try:
				results = resp.json()['results']
			except KeyError:
				print('Error: OctopusEnergy: No "results" in API response')
				raise

			# Returns the first one found. There's now an EXPORT version of the
			# Agile Octopus tariff which is for selling back to the grid - we don't want
			# that one.
			productCodes = []
			
			for obj in results:
				if obj['code'][:5] == 'AGILE' and obj['direction'] == 'IMPORT':
					productCodes.append(obj['code'])
					
			# None found, so raise exception.
			if len(productCodes) == 0:
				raise APIError('Error: Import Product code starting with AGILE has not been found')

			# If we found more than one, I need to know because the picture has changed
			# and the returns from this code might not be reliable any more.
			if len(productCodes) > 1:
				print("Error: OctopusEnergy: warning - multiple product codes starting with AGILE \
					were found: {}".format(productCodes))
					
			self.productCode = productCodes[0]
			
			if self.noisy:
				print('OctopusEnergy: product code detected as {}'.format(self.productCode))

		return self.productCode
		

	# Retrieve the tariff code for the product, and the distribution company responsible
	# for the user's postcode.
	def octopusGetTariffCode(self):
	
		if self.tariffCode == None:
			url = self.baseURL + 'products/' + self.octopusGetProductCode() + '/'
			
			if self.noisy:
				print('Debug: OctopusEnergy: attempting to get tariff code from API')
			
			try:
				resp = requests.get(url)
			except requests.exceptions.RequestException as e:
				print('Error: OctopusEnergy: Tariff retrieve from Octopus API failed: {}'.format(str(e)))
				raise
			
			try:
				self.tariffCode = resp.json()['single_register_electricity_tariffs'][self.distributorCode]['direct_debit_monthly']['code']
			except requests.exceptions.RequestException as e:
				print('Error: OctopusEnergy: Could not retrieve tariff from API results: {}'.format(str(e)))
				raise

		if self.noisy:
			print('Debug: OctopusEnergy: tariff code detected as {}'.format(self.tariffCode))

		return self.tariffCode
		
		
	# Retrieve tariff costs from API. Handles pagination in the API.
	# Timings look like: {'period_from': '2019-05-11T12:00', 'period_to': '2019-05-12T23:30'}
	# c/f t.strftime('%Y-%m-%dT%H:%M')
	def octopusGetTariffCosts(self, timings):
		
		uktz = timezone('Europe/London')
		
		if self.tariffCosts.empty:
		
			# Initialise empty DataFrame
			df = pd.DataFrame()
   
			url = self.baseURL + 'products/' + self.octopusGetProductCode() + '/electricity-tariffs/' + self.octopusGetTariffCode() + '/standard-unit-rates/'
		
			sleepTime = 0.1
		
			# May want more params at some point.
			params = timings
		
			if self.noisy:
				print('Debug: OctopusEnergy: attempting to get tariff costs from API')

			resp = requests.get(url, params=params)
		
			nextPage = resp.json()['next']
	
			# Now retrieve pages until the next page is returned as'None' 
			while nextPage != None:

				df_tmp = pd.DataFrame(resp.json()['results'])
		
				if df.empty:
					df = df_tmp
				else:
					df = df.append(df_tmp)
		
				if self.noisy:
					print('Debug: OctopusEnergy: Retrieved {} rows, total now {}'.format(len(df_tmp), len(df)))
		
				time.sleep(sleepTime)
		
				resp = requests.get(nextPage)
			
				nextPage = resp.json()['next']
	
			# Add the last page retrieved to the result.
			df_tmp = pd.DataFrame(resp.json()['results'])
	
			# Still need this check, in case it was just one page and the loop body
			# was skipped.
			if df.empty:
				df = df_tmp
			else:
				df = df.append(df_tmp)
		
			if self.noisy:
				print('Debug: OctopusEnergy: Retrieved {} rows, total is {}'.format(len(df_tmp), len(df)))
	
			for col in ['valid_from', 'valid_to']:
				df[col] = pd.to_datetime(df[col])
	
		
			df = df.set_index('valid_from')
	
			self.tariffCosts = df.drop('value_exc_vat', axis=1)
			self.tariffCostLastRefresh = dt.datetime.now(timezone('Europe/London'))
		
			if self.noisy:
				print('Debug: OctopusEnergy: I have {} tariff costs from API'.format(len(self.tariffCosts)))
		
		return self.tariffCosts

	# Get the cheapest x minute slot
	def getCheapestSlot(self, mins):
	
		if self.noisy:
			print('Debug: OctopusEnergy: Calculating cheapest {} minute time slot'.format(mins))
			
		# Minimum time slot.
		if mins < 30:
			mins = 30

		# We don't have data for requests longer than 40 hours, so no point looking it up
		if mins > 40*60:
			raise RequestedSlotTooLongError

		costs = self.octopusGetTariffCosts(self.nowUntilTomorrow()).copy()
		
		# Meaningless to find a slot taking up more than 80% of the time for which there
		# is data.
		if mins > len(costs) * 30 * .8:
			raise RequestedSlotTooLongError
			
		slots = round(mins/30)
		
		if slots > 1:
			c = costs['value_inc_vat'].rolling(slots).mean().dropna().sort_values().head(n=1)
		else:
			c = costs['value_inc_vat'].sort_values().head(n=1)
				
		return(c.index[0].to_pydatetime(), (c.index[0] + dt.timedelta(minutes=slots*30)).to_pydatetime())
			
if __name__ == '__main__':

	o = OctopusEnergy('LS29 8HF', noisy=True)
	
	if o.noisy:
		print(o.octopusGetProductCode())
		print(o.octopusGetTariffCode())
		print(o.nowUntilTomorrow())
		print(o.octopusGetTariffCosts(o.nowUntilTomorrow()))
	tz = timezone('Europe/London')
	for t in 30, 60, 90, 120, 240:
		(start, end) = o.getCheapestSlot(t)
		print('{}m: {}-{}'.format(t, start.astimezone(tz).strftime('%a %H:%M'), end.astimezone(tz).strftime('%H:%M')))
