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


class OctopusEnergy:

	octopusAPIVersion = '1'
	postCodeLookupFile = 'PC2ED.csv'
	baseURL = 'https://api.octopus.energy/v' + octopusAPIVersion + '/'
	
	productCode = None
	tariffCode = None
	tariffCosts = None
	tariffCostLastRefresh = None

	def __init__(self, postcode, noisy=False):
	
		nonAlphaRE = re.compile('[^A-Z0-9]+')
		
		# Initialise some instance variables.
		self.postcode = nonAlphaRE.sub('', str(postcode).upper())
		self.lookupTable = None # postcode to electricity distributor lookup
		self.productCode = None # Octopus Energy product code for Agile Octopus
		self.tariffCode = None # Octopus Energy tariff code for user, derived from their postcode
		self.noisy = noisy
		
	# Return time period parameters for the API going from now until tomorrow night.
	# Return format is params which can be plugged into API call
	def nowUntilTomorrow(self):
		
		t = dt.datetime.now(timezone('Europe/London'))

		# if we're in the first half hour of an hour, then start on the next half hour.
		# if we're in the second half hour of an hour, then start on the next hour.

		# Might be nice to push to next slot if very close to the start of this one,
		# but that's a future enhancement at this stage.
		if t.minute < 30:
			t = dt.datetime(t.year, t.month, t.day, t.hour, 30, 0)
		else:
			t = t + dt.timedelta(hours=1)
			t = dt.datetime(t.year, t.month, t.day, t.hour, 0, 0)

		tomorrow = (dt.date.today() + dt.timedelta(1)).strftime('%Y-%m-%dT23:30')	 
		today = t.strftime('%Y-%m-%dT%H:%M')

		return {
			'period_from': today, 'period_to': tomorrow
		}
	
	# Return the distributor code (something looking a bit like _M for the user's postcode)
	def distributorLookup(self):

		# First part of postcode is all we need.
		pcprefix = self.postcode[:-3]

		# Only want to do this once.
		if self.lookupTable == None:
			self.lookupTable = pd.read_csv(self.postCodeLookupFile, index_col='PostCode')
		
		try:
			result = self.lookupTable.loc[pcprefix]
		except KeyError:
			print('OctopusEnergy: Postcode not found - {}'.format(pcprefix))
			raise
			
		if self.noisy:
			print('OctopusEnergy: found distributor code letter as {}'.format(result.AreaCodeLetter))
			
		return result.AreaCodeLetter
		
	# Get the "agile" product code. Currently there's only one, but this will need to 
	# be revisited if more appear, so as to figure out which one to use. Currently 
	# the first one returned is used.
	def octopusGetProductCode(self):
	
		if self.productCode == None:
	
			url = self.baseURL + 'products/'
		
			if self.noisy:
				print('OctopusEnergy: attempting to get product code from API')
				
			try:
				resp = requests.get(url, params={'is_tracker': True})
			except requests.exceptions.RequestException as e:
				print('OctopusEnergy: Product code retrieve from Octopus API failed: {}'.format(str(e)))
				raise
		
			try:		
				results = resp.json()['results']
			except KeyError:
				print('OctopusEnergy: No "results" in API response')
				raise
				
			if len(results) > 1:
				print('OctopusEnergy: More than one product code came back (there were {})'.format(len(resp.json()['results'])))
			
			self.productCode = results[0]['code']
		
			if self.noisy:
				print('OctopusEnergy: product code detected as {}'.format(self.productCode))

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
				self.tariffCode = resp.json()['single_register_electricity_tariffs'][self.distributorLookup()]['direct_debit_monthly']['code']
			except requests.exceptions.RequestException as e:
				print('OctopusEnergy: Could not retrieve tariff from API results: {}'.format(str(e)))
				raise

		if self.noisy:
			print('OctopusEnergy: tariff code detected as {}'.format(self.tariffCode))

		return self.tariffCode
		
		
	# Retrieve tariff costs from API. Handles pagination in the API.
	def octopusGetTariffCosts(self):
		
		uktz = timezone('Europe/London')
		
		# We only need to retrieve these once per hour, unless it's the first attempt
		# where the hour is 4pm, when the data is refreshed..
		if self.tariffCostLastRefresh != None:

			if self.tariffCostLastRefresh.hour == 15 and dt.datetime.now(tz=uktz).hour == 16:
				_
			else:
				nextRefresh = self.tariffCostLastRefresh + dt.timedelta(hours=1)

				if nextRefresh > dt.datetime.now(uktz):
					if self.noisy:
						print('OctopusEnergy: reusing tariff costs from before')
					return self.tariffCosts
					
		# Initialise empty DataFrame
		df = pd.DataFrame()
   
		url = self.baseURL + 'products/' + self.octopusGetProductCode() + '/electricity-tariffs/' + self.octopusGetTariffCode() + '/standard-unit-rates/'
		
		sleepTime = 0.3
		params = self.nowUntilTomorrow()
		
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

		costs = self.octopusGetTariffCosts().copy()

		if mins > len(costs) * 30 * .8:
			return None # not going to find a slot taking up more than 80% of the time left
			
		slots = round(mins/30)
		
		if slots > 1:
			c = costs['value_inc_vat'].rolling(slots).mean().dropna().sort_values().head(n=1)
		else:
			c = costs['value_inc_vat'].sort_values().head(n=1)
				
		return(c.index[0].to_pydatetime(), (c.index[0] + dt.timedelta(minutes=slots*30)).to_pydatetime())
			
if __name__ == '__main__':

	o = OctopusEnergy('LS29 8ST', noisy=False)
	
	if o.noisy:
		print(o.octopusGetProductCode())
		print(o.octopusGetTariffCode())
		print(o.octopusGetTariffCosts())
		print(o.nowUntilTomorrow())
	tz = timezone('Europe/London')
	for t in 30, 60, 90, 120, 240:
		(start, end) = o.getCheapestSlot(t)
		print('{}m: {}-{}'.format(t, start.astimezone(tz).strftime('%a %H:%M'), end.astimezone(tz).strftime('%H:%M')))
