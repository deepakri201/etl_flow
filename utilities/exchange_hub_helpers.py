#
# Copyright 2020, Institute for Systems Biology
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json

import requests
import logging


# from http.client import HTTPConnection
# HTTPConnection.debuglevel = 0
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# rootlogger = logging.getLogger('root')
# errlogger = logging.getLogger('root.err')

# from python_settings import settings
import settings
import logging
logging.getLogger("requests").setLevel(logging.WARNING)

def post(url, data):
    result =  requests.post(url, data=data)
    response = result.json()
    if result.status_code != 200:
        raise RuntimeError('In get_url(): status_code=%s; url: %s', result.status_code, url)
    return result

def create_exchange():
    url = 'https://analyticshub.googleapis.com/v1/projects/nci-idc-bigquery-data/locations/US/dataExchanges?dataExchangeId=nci_idc_bigquery_data_exchange'
    data = {
        "displayName": "nci-idc-bigquery-data-exchange",
        "description": "Exchange for publication of NCI IDC BQ datasets",
        "primaryContact": "bcliffor@systemsbiology.org"
    }

    headers = {
        "Authorization": "Bearer  }
    result =  requests.post(url, data=json.dumps(data), headers=headers)
    response = result.json()
    if result.status_code != 200:
        raise RuntimeError('In get_url(): status_code=%s; url: %s', result.status_code, url)
    return (response)

if __name__ == "__main__":
    r = create_exchange()


