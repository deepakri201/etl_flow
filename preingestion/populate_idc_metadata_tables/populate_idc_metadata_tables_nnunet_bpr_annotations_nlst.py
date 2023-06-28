#
# Copyright 2015-2021, Institute for Systems Biology
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

# Adds/replaces data to the idc_collection/_patient/_study/_series/_instance DB tables
# from a specified bucket.
#
# For this purpose, the bucket containing the instance blobs is gcsfuse mounted, and
# pydicom is then used to extract needed metadata.
#
# The script walks the directory hierarchy from a specified subdirectory of the
# gcsfuse mount point

import io
import os
import sys
import argparse
import pathlib
import subprocess

from python_settings import settings
from populate_idc_metadata_tables import prebuild
from google.cloud import storage

if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--version', default=settings.CURRENT_VERSION)
    parser.add_argument('--src_bucket', default='nnunet-bpr-annotations', help='Bucket containing WSI instances')
    parser.add_argument('--mount_point', default='/mnt/disks/idc-etl/nnunet-bpr-annotations', help='Directory on which to mount the bucket.\
                The script will create this directory if necessary.')
    parser.add_argument('--subdir', default='version_4/nlst', help="Subdirectory of mount_point at which to start walking directory")
    parser.add_argument('--collection_id', default='NLST', help='idc_webapp_collection id of the collection or ID of analysis result to which instances belong.')
    parser.add_argument('--wiki_doi', default='10.5281/zenodo.7975081', help='Collection DOI')
    parser.add_argument('--wiki_url', default='https://zenodo.org/record/7975081',\
                        help='Info page URL')
    parser.add_argument('--license', default = {"license_url": 'https://creativecommons.org/licenses/by/4.0/',\
            "license_long_name": "Creative Commons Attribution 4.0 International License", \
            "license_short_name": "CC BY 4.0"})
    parser.add_argument('--third_party', type=bool, default=True, help='True if from a third party analysis result')
    parser.add_argument('--gen_hashes', default=True, help=' Generate hierarchical hashes of collection if True')

    args = parser.parse_args()
    print("{}".format(args), file=sys.stdout)
    args.client=storage.Client()

    try:
        # gcsfuse mount the bucket
        pathlib.Path(args.mount_point).mkdir( exist_ok=True)
        subprocess.run(['gcsfuse', '--implicit-dirs', args.src_bucket, args.mount_point])
        prebuild(args)
    finally:
        # Always unmount
        subprocess.run(['fusermount', '-u', args.mount_point])
