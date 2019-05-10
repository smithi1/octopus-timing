# octopus-timing
I am a customer of Octopus Energy's Agile Octopus tariff, which is a dynamic tariff with pricing for each half hour slot in the day. It's currently only in the UK, so apologies to everyone else. I want to find the cheapest time of day in which to run intensive electrical loads that consume a lot of power over time. For example, our washing machine takes about 90 minutes to do a full cycle, and I want to know when the cheapest 90 minute slot will be.

This is a Lambda function which supports an Alexa skill that I can use to find out this information.

It's far from a mature product, and it will require hacking on your part to get it working. If you're not on Octopus Energy, this won't be much use to you. If you get all excited about [their API](https://developer.octopus.energy/docs/api/#agile-octopus) and decide to sign up please consider using [my referral link](https://share.octopus.energy/pale-cobra-742). At the time of writing, we'd both get a £50 credit if you do!

### Examples of Use

"Alexa, ask Octopus for the cheapest 3 hour slot"
 - "The cheapest 3 hour slot runs from 1pm to 4pm"

"Alexa, ask Octopus for the cheapest 90 minute slot"
 - "The cheapest 90 minute slot runs from 2:30pm to 4pm"

### AWS Lambda Setup

The code itself is fairly small, but it makes use of packages that are not available  by default in the Lambda Python 3.7 environment. The following high level steps are required to get it up and running:

1. Create custom layers in the Lambda console, to allow the module access to the Python 3.7 modules listed in `requirements.txt` (and their dependencies). AWS provide a layer called `AWSLambda-Python37-SciPy1x` which contains numpy and I've provided two more custom layer files - one containing pytz and Pandas (without numpy) and the other with Ask-Flask plus dependencies.  Use mine or build your own, your choice.
2. Create a new Lambda function, and add the three layers, with the Alexa Skills Kit as the trigger, and provisioned access to CloudWatch logs.
3. Create a zip file containing the `octopus` folder, `lambda_function.py` and `PC2ED.csv` , and upload using the "Function code" area of the skill editor, and ensure that the runtime is Python 3.7, and the handler box reads `lambda_function.lambda_handler`. You can also use the code editor provided to have an editable version of the code in there.
4. Create an environment variable `MY_POSTCODE` in the Lambda function config page and set it to your postcode. (See also to-do item below). The skill will generate log messages and provide answers for Ilkley Post Office if you don't do this. If you live near Ilkley, this might work fine for you.

 The code requires the `octopus` folder, `lambda_function.py`, and `PC2ED.csv` to be  present.

### Alexa Developer Console Setup

This isn't a detailed set of instructions, but it should be possible to figure out what I've done even if you're reasonably new to this.

1. Create a new skill in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Paste the JSON from the included "interaction_model.json" file into the JSON editor for your interaction model in the skill Build page. Review and hack about with the resulting intents, utterances, etc.
3. Add the Amazon Resource Number for your Lambda function into the "Endpoint" tab of the skill build page.
4. Move to the Test tab, and see if it works. When it doesn't work, look in the CloudWatch logs to see what is going on with your Lambda function. The `print()` statements in the code should produce log entries. Add your own if you need more!

### To-Do

In no particular order...

* Write something to deploy this automatically.
* Change the function that returns the environment variable postcode to make it retrieve the user's postcode and use that instead. The first part of the postcode is used to find out which electricity region the user is in, so that the right pricing information is used.
* Give some consideration to removing Pandas - I think that might be very good for the cold start time, as it removes the need for two of the three layers to be unpacked. I'm mostly using it for fairly simple stuff - the most significant thing is using rolling windows to find out when the cheapest time slot of the required length is.