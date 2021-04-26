# Importing libraries
# You need a custom Lambda layer with requests and lxml, as these aren't included in the default Lambda layer.

import json
import requests as r
from lxml import html
import os
from datetime import datetime as dt

# You need to have the API key for the MOT API to make this work
# This should be set as an environment variable

MOT_API_KEY = os.environ.get("MOT_API_KEY")


def lambda_handler(event, context=None):
    # Read in the vrn (vehicle registration number) input from APIG event
    vrn = event['queryStringParameters']['vrn']

   # Create an empty response dict for us to add to later
    resp_body = {}

   # Most of the code in this function is for scraping data from the Clean Air Zone vehicle checker
   # to see whether a vehicle would be charged for entering the Birmingham Clean Air Zone.

   # There is no API available for this information.

   # It uses the requests library to make HTTP requests, and lxml to parse the responses.

   # There are a number of requests and responses in the process that it goes through - try the website yourself
   # to see what the process looks like.

    # Set up a session - not quite sure why, but it allows certain things to persist between responses
    client = r.session()

   # The site is fussy about the user agent, so I've put this one in - anything reasonable should work
    client.headers = {
        "User-Agent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Safari/537.36; TfWM Innovation (innovation@tfwm.org.uk)'}

   # Making the first request
    URL = "https://vehiclecheck.drive-clean-air-zone.service.gov.uk/vehicle_checkers/enter_details"
    resp = client.get(URL)

   # This is where lxml comes in - we can look at the content later
    root = html.fromstring(resp.content)

    # Extract the CSRF token from the HTML, which will be used later
   # Otherwise, the vehicle checker will reject our requests.
    authenticity_token = root.xpath(
        '/html/head/meta[@name="csrf-token"]/@content')[0]

    # Build the form body which will be sent with the first substantive request
   # we're using the CSRF token in here
    data = {"vrn": vrn,
            "registration-country": "UK",
            "commit": "Continue",
            "authenticity_token": authenticity_token
            }

    # Use the previous URL as the referer
    headers = {"Referer": URL}

    resp = client.post(URL, data=data, headers=headers)
    root = html.fromstring(resp.content)

    # Check if the vehicle has not been found by the checker
    not_found = root.xpath(
        'boolean(//h1[@class="govuk-heading-l not-found-title"])')

    if not_found:
        charged_status = None
      # Adding some more information to the API response, just to be nice
        resp_body['error'] = "not_found"
        resp_body['error_text'] = "Vehicle details could not be found"

    else:
        # Extracting vehicle information from the page returned, and putting it in the response
        for x in ['registration-number', 'type-approval', 'type', 'make', 'model', 'colour', 'fuel-type']:
            try:
                resp_body[x] = root.xpath(f'//th[@id="{x}"]/text()')[0]
            except IndexError:
                pass

        # Preparing the form body for the next request
        # Discovered this from looking at the requests being made on the website
        data = {"authenticity_token": authenticity_token,
                "confirm_details_form[undetermined]": "false",
                "confirm_details_form[taxi_and_correct_type]": "true",
                "confirm_details_form[confirm_details]": "yes",
                "confirm_details_form[confirm_taxi_or_phv]": "false",
                "commit": "Confirm"
                }
        resp = client.post(
            "https://vehiclecheck.drive-clean-air-zone.service.gov.uk/vehicle_checkers/confirm_details",
            data=data,
            headers=headers)

        root = html.fromstring(resp.content)

        # Here, we're extracting the actual results from the table on the final page
        texts = root.xpath(f'//tr')
        for text in texts:
            try:
                # Putting the text in each column into a variable - we only care about the first two
                city, charge, *_ = (text.xpath('td/text()'))
            except ValueError:
                continue
            if city == 'Birmingham':
                # Translating the text into a variable
                uncharged = (charge.strip().rstrip() == 'No Charge')
                charged = (charge.strip().rstrip() == "£8.00")

        # A few simple checks
        # If something isn't right (like there's no match), set the response to None
        # This will raise an error over on Power Automate, as it doesn't match schema.
        if charged and uncharged:
            charged_status = None
        elif charged:
            charged_status = True
        elif uncharged:
            charged_status = False
        else:
            charged_status = None

    # Add the vrn and charged status to the response
    resp_body["vrn"] = vrn
    resp_body["charged"] = charged_status

    # Collecting data from the MOT API and put that in the response
    j = r.get("https://beta.check-mot.service.gov.uk/trade/vehicles/mot-tests",
              params={"registration": vrn},
              headers={"X-Api-Key": MOT_API_KEY}).json()

    resp_body["mot_data"] = j

    # I've removed the below code as we're not using it any more - it just wasn't accurate enough
    # There is some alternative code in some of the scripts that we're using for

    #  try:
    #      mileages = [(int(x['odometerValue']), dt.strptime(x['completedDate'], "%Y.%m.%d %H:%M:%S")) for x in j[0]['motTests']]
    #      mileages = sorted(mileages, key=lambda x:x[1], reverse=True)
    #      years = (mileages[0][1] - mileages[1][1]).total_seconds() / (3600*24*365)
    #      mileage_difference = mileages[0][0] - mileages[1][0]
    #      resp_body["last_year_mileage"] = int(mileage_difference / years)
    #  except (IndexError, KeyError):

    # This is just retained so the response meets the schema that Power Automate is expecting
    resp_body["last_year_mileage"] = 0


    # Build the response and return it to APIG
    resp = {"isBase64Encoded": False,
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(resp_body, indent=4)
            }

    return resp
