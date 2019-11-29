import gzip
import json
import base64
import boto3
import os

# Lambda function that streams CloudWatch logs to a Simple Notification Service queue. 

# 1. Create an SNS topic and set it up to notify you however you wish.
# 2. Create your Lambda function to host this code. Ensure the role that goes along with
#    this allows publishing to your SNS topic. Put the ARN for the topic in the SNS_ARN
#    environment variable for your Lambda function. Set the NOTIFICATION_PREAMBLE
#    environment variable to a short string to indicate at the start of your notification
#    what the rest of the message is, e.g. "Alexa Skill Lambda"
# 3. Create a lambda subscription filter in your CloudWatch log group. You can set this
#    up to filter particular error strings, so your function only gets called for things
#    you're interested in, and point it to your Lambda function.

def lambda_handler(event, context):
    
    snsARN = os.environ['SNS_ARN']
    
    sns = boto3.client('sns')
    
    cw_data = event['awslogs']['data']

    # unpack the payload
    compressed_payload = base64.b64decode(cw_data)
    uncompressed_payload = gzip.decompress(compressed_payload)
    payload = json.loads(uncompressed_payload)
    log_events = payload['logEvents']
    
    message = ""
    
    # send the messages - this loop removes any duplicates.
    for log_event in log_events:
        if message == "" or message != log_event['message']:
            message = log_event['message']
            response = sns.publish(
                TopicArn=snsARN,    
                Message=os.environ['NOTIFICATION_PREAMBLE'] + " " + log_event['message']    
            )
    