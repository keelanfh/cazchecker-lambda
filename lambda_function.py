import json
import requests as r
from lxml import html
import os
from datetime import datetime as dt

MOT_API_KEY = os.environ.get("MOT_API_KEY")

def lambda_handler(event, context=None):
    # Process input from APIG event
    vrn = event['queryStringParameters']['vrn']
    resp_body = {}

    # Set up session and make the first request (just a GET to the first page)
    client = r.session()
    
    # Need to provide a reasonable user agent in here - include email address for politeness
    client.headers = {"User-Agent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Safari/537.36; TfWM Innovation (innovation@tfwm.org.uk)'}
    
    URL = "https://vehiclecheck.drive-clean-air-zone.service.gov.uk/vehicle_checkers/enter_details"
    resp = client.get(URL)
    root = html.fromstring(resp.content)

    # Extract the CSRF token from the HTML, which will be used later
    authenticity_token = root.xpath(
        '/html/head/meta[@name="csrf-token"]/@content')[0]

    # Build the form body which will be sent with the first substantive request
    data = {"vrn": vrn,
            "registration-country": "UK",
            "commit": "Continue",
            "authenticity_token": authenticity_token
            }

    # Use the previous URL as the referer
    headers = {"Referer": URL}

    resp = client.post(URL, data=data, headers=headers)
    root = html.fromstring(resp.content)


    # Check if a 'not found' response is returned, and respond if this is the case
    not_found = root.xpath(
        'boolean(//h1[@class="govuk-heading-l not-found-title"])')

    if not_found:
        charged_status = None
        resp_body['error'] = "not_found"
        resp_body['error_text'] = "Vehicle details could not be found"

    else:
        # Extracting vehicle information from the page returned
        for x in ['registration-number', 'type-approval', 'type', 'make', 'model', 'colour', 'fuel-type']:
            try:
                resp_body[x] = root.xpath(f'//th[@id="{x}"]/text()')[0]
            except IndexError:
                pass

        # Preparing the form body for the next request
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

        texts = root.xpath(f'//tr')
        for text in texts:
            try:
                city, charge, *_ = (text.xpath('td/text()'))
            except ValueError:
                continue
            if city == 'Birmingham':
                uncharged = (charge.strip().rstrip() == 'No Charge')
                charged = (charge.strip().rstrip() == "£8.00")


        # A few simple checks
        if charged and uncharged:
            charged_status = None
        elif charged:
            charged_status = True
        elif uncharged:
            charged_status = False
        else:
            charged_status = None

    resp_body["vrn"] = vrn
    resp_body["charged"] = charged_status
    
    j = r.get("https://beta.check-mot.service.gov.uk/trade/vehicles/mot-tests",
              params={"registration": vrn},
              headers={"X-Api-Key": MOT_API_KEY}).json()
              
    resp_body["mot_data"] = j
    
    try:
        mileages = [(int(x['odometerValue']), dt.strptime(x['completedDate'], "%Y.%m.%d %H:%M:%S")) for x in j[0]['motTests']]
        mileages = sorted(mileages, key=lambda x:x[1], reverse=True)
        years = (mileages[0][1] - mileages[1][1]).total_seconds() / (3600*24*365)
        mileage_difference = mileages[0][0] - mileages[1][0]
        resp_body["last_year_mileage"] = int(mileage_difference / years)
    except (IndexError, KeyError):
        resp_body["last_year_mileage"] = 0


    # Build the response
    resp = {"isBase64Encoded": False,
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(resp_body, indent=4)
            }

    return resp
