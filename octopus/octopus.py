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

postCodeLookupFile = 'PC2ED.csv'

class APIError(Exception):
	pass

class OctopusEnergy:

	octopusAPIVersion = '1'
	baseURL = 'https://api.octopus.energy/v' + octopusAPIVersion + '/'
	
	productCode = None
	tariffCode = None
	tariffCosts = None

	def __init__(self, postcode=None, distributorCode=None, noisy=False):
	
		if all(v is None for v in {postcode, distributorCode}):
			raise ValueError('Expected either postcode or distributorCode')
	
		self.noisy = noisy
		self.productCode = None # Octopus Energy product code for Agile Octopus
		self.tariffCode = None # Octopus Energy tariff code for user, derived from their postcode
	
		# Postcode lookup table
		lookupTable = pd.read_csv(postCodeLookupFile)
			
		# Handle distributorCode
		if distributorCode == None:
			self.distributorCode = None
		else: 
			# Check it's a distributor code that we know about.
			if distributorCode not in lookupTable['AreaCodeLetter'].unique():
				raise ValueError('"' + distributorCode + '" is not a known distributorCode')
				
			# Remember it	
			self.distributorCode = distributorCode
			
			# Ignore any postcode that has been supplied, it's redundant.
			postcode = None
			
			if self.noisy:
				print('OctopusEnergy: Known distributorCode supplied as {}, ignoring any supplied postcode'.format(distributorCode))
	
		# Handle postcode
		if postcode == None:
			self.postcode = None
		else:
			nonAlphaRE = re.compile('[^A-Z0-9]+')

			self.postcode = nonAlphaRE.sub('', str(postcode).upper())[:-3]
			
			if lookupTable['PostCode'].loc[lookupTable['PostCode'] == self.postcode].count() != 1:
				raise ValueError('"' + postcode + '" is not a known postcode')
				
			self.distributorCode = lookupTable.loc[lookupTable['PostCode'] == self.postcode]['AreaCodeLetter'].min()
			
			if self.noisy:
				print('OctopusEnergy: Postcode supplied as {}, distributor code looked up as {}'.format(self.postcode, self.distributorCode))

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
				print('OctopusEnergy: attempting to get product code from API')
				
			try:
				resp = requests.get(url)
			except requests.exceptions.RequestException as e:
				print('OctopusEnergy: Product code retrieve from Octopus API failed: {}'.format(str(e)))
				raise
		
			try:		
				results = resp.json()['results']
			except KeyError:
				print('OctopusEnergy: No "results" in API response')
				raise

			# Still only returns the first one found.
			for obj in results:
				if obj['code'][:5] == 'AGILE':
					self.productCode = obj['code']
					if self.noisy:
						print('OctopusEnergy: product code detected as {}'.format(self.productCode))
					return self.productCode
			
			raise APIError('Product code starting with AGILE has not been found')

		else:
			return self.productCode
		

	# Retrieve the tariff code for the product, and the distribution company responsible
	# for the user's postcode.
	def octopusGetTariffCode(self):
	
		if self.tariffCode == None:
			url = self.baseURL + 'products/' + self.octopusGetProductCode() + '/'
			
			if self.noisy:
				print('OctopusEnergy: attempting to get tariff code from API')
			
			try:
				resp = requests.get(url)
			except requests.exceptions.RequestException as e:
				print('OctopusEnergy: Tariff retrieve from Octopus API failed: {}'.format(str(e)))
				raise
			
			try:
				self.tariffCode = resp.json()['single_register_electricity_tariffs'][self.distributorCode]['direct_debit_monthly']['code']
			except requests.exceptions.RequestException as e:
				print('OctopusEnergy: Could not retrieve tariff from API results: {}'.format(str(e)))
				raise

		if self.noisy:
			print('OctopusEnergy: tariff code detected as {}'.format(self.tariffCode))

		return self.tariffCode
		
		
	# Retrieve tariff costs from API. Handles pagination in the API.
	# Timings look like: {'period_from': '2019-05-11T12:00', 'period_to': '2019-05-12T23:30'}
	# c/f t.strftime('%Y-%m-%dT%H:%M')
	def octopusGetTariffCosts(self, timings):
		
		uktz = timezone('Europe/London')
					
		# Initialise empty DataFrame
		df = pd.DataFrame()
   
		url = self.baseURL + 'products/' + self.octopusGetProductCode() + '/electricity-tariffs/' + self.octopusGetTariffCode() + '/standard-unit-rates/'
		
		sleepTime = 0.3
		
		# May want more params at some point.
		params = timings
		
		if self.noisy:
			print('OctopusEnergy: attempting to get tariff costs from API')

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
				print('OctopusEnergy: Retrieved {} rows, total now {}'.format(len(df_tmp), len(df)))
		
			time.sleep(sleepTime)
		
			resp = requests.get(nextPage)
			
			nextPage = resp.json()['next']
	
		# Add the last page retrieved to the result.
		df_tmp = pd.DataFrame(resp.json()['results'])
	
		# Still need this check, in case it was just one page.
		if df.empty:
			df = df_tmp
		else:
			df = df.append(df_tmp)
		
		if self.noisy:
			print('OctopusEnergy: Retrieved {} rows, total	is {}'.format(len(df_tmp), len(df)))
	
		for col in ['valid_from', 'valid_to']:
			df[col] = pd.to_datetime(df[col])
	
		
		df = df.set_index('valid_from')
	
		self.tariffCosts = df.drop('value_exc_vat', axis=1)
		self.tariffCostLastRefresh = dt.datetime.now(timezone('Europe/London'))
		
		if self.noisy:
			print('OctopusEnergy: I have {} tariff costs from API'.format(len(self.tariffCosts)))
		
		return self.tariffCosts

	# Get the cheapest x minute slot
	def getCheapestSlot(self, mins):
	
		if self.noisy:
			print('OctopusEnergy: Calculating cheapest {} minute time slot'.format(mins))
			
		# Minimum time slot.
		if mins < 30:
			mins = 30

		costs = self.octopusGetTariffCosts(self.nowUntilTomorrow()).copy()

		if mins > len(costs) * 30 * .8:
			return None, None # not going to find a slot taking up more than 80% of the time left
			
		slots = round(mins/30)
		
		if slots > 1:
			c = costs['value_inc_vat'].rolling(slots).mean().dropna().sort_values().head(n=1)
		else:
			c = costs['value_inc_vat'].sort_values().head(n=1)
				
		return(c.index[0].to_pydatetime(), (c.index[0] + dt.timedelta(minutes=slots*30)).to_pydatetime())
			
if __name__ == '__main__':

	o = OctopusEnergy('LS29 8HF', noisy=False)
	
	if o.noisy:
		print(o.octopusGetProductCode())
		print(o.octopusGetTariffCode())
		print(o.octopusGetTariffCosts())
		print(o.nowUntilTomorrow())
	tz = timezone('Europe/London')
	for t in 30, 60, 90, 120, 240:
		(start, end) = o.getCheapestSlot(t)
		print('{}m: {}-{}'.format(t, start.astimezone(tz).strftime('%a %H:%M'), end.astimezone(tz).strftime('%H:%M')))
