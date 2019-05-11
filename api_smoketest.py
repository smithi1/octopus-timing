# This exercises all of the OctopusEnergy functionality via a supplied postcode
# and also via a supplied distributorCode.

from pytz import timezone

from octopus.octopus import OctopusEnergy

tz = timezone('Europe/London')
noisy = True
t = 90

# With postcode...
o = OctopusEnergy(postcode = 'LS29 8HF', noisy=noisy)
(start, end) = o.getCheapestSlot(t)
print('{}m: {}-{}'.format(t, start.astimezone(tz).strftime('%a %H:%M'), end.astimezone(tz).strftime('%H:%M')))
print('Incidentally, nowUntilTomorrow() = {}\n'.format(o.nowUntilTomorrow()))


# With distributorCode 
o = None
o = OctopusEnergy(distributorCode = '_M', noisy=noisy)
(start, end) = o.getCheapestSlot(t)
print('{}m: {}-{}\n'.format(t, start.astimezone(tz).strftime('%a %H:%M'), end.astimezone(tz).strftime('%H:%M')))

# With neither (exception should be raised)
o = None
try:
	o = OctopusEnergy(noisy=noisy)
except ValueError as e:
	print('Correct failure occurred: ' + str(e))

if o != None:
	print('Got an object back, despite no parameters - this is a fail...')
