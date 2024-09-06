from flask import request as flask_request, Flask,jsonify
import requests
import urllib
from requests.structures import CaseInsensitiveDict

from pprint import pprint
from bs4 import BeautifulSoup
import multiprocessing
import time
from dotenv import load_dotenv
import os
import threading
import pandas as pd
import numpy as np
import os
from py_olamaps.OlaMaps import OlaMaps
from openai import OpenAI
import subprocess
from flask_cors import CORS


load_dotenv('env')
CLIENT_ID = os.getenv('MAPPLS_CLIENT_ID')
CLIENT_SECRET = os.getenv('MAPPLS_CLIENT_SECRET')
SUBDOMAIN = "postmitra"
PORT = 8000

class DUMMY_MODE:
    FLAG=False
    DUMMY_IMAGE_URL = "https://cdn.collectorbazar.com/products/india-postal-envelope-registered-letter-commerially-used-g18657-268009-1.jpg"
    DUMMY_RESPONSE = {
        "parsed_address": "Hindustan Lever Ltd., Express Building 1st Floor, Bahadur Shah Zafer Marg, P.O. Box. 7003,, NEW DELHI - 110002",
        "pincode": "110002",
        "post_address": None,
        "post_lat": 28.6284722,
        "post_long": 77.2445555,
        "receiver_adddress": "9,10, Express Building, Bahadur Shah Zafar Marg, Indraprastha Estate, Darya Ganj, Central District, New Delhi, Delhi, 110002",
        "receiver_lat": "28.633115",
        "receiver_long": "77.241392"
    }
    
class MMI:
    def __init__(self, client_id, client_secret):
        self.authorization_header = self.get_authorization_header(client_secret=client_secret,client_id=client_id)
        self.client_id = client_id
        self.client_secret = client_secret
        self.df : pd.DataFrame = pd.read_pickle('pincode.pkl')
        self.ola_client = OlaMaps(
            api_key=os.environ.get("OLA_MAPS_API_KEY"),
        )
        self.gpt_client = OpenAI()

    def get_geo_coded_data(self,address):
        encoded_address = address
        
        url = f'https://atlas.mappls.com/api/places/geocode?region=ind&address={encoded_address}&itemCount=1&bias=0'
        retry_authentication = True
        while True:
            response = requests.get(url, headers=self.authorization_header)
            if response.status_code == 200:
                return {
                    'status' : 'success',
                    'status_code' : response.status_code,
                    'response' : response.json()['copResults']
                }
            elif response.status_code == 204:
                return {
                    'status' : 'Address not found',
                    'status_code' : response.status_code,
                    'response' : response
                }
            elif response.status_code == 401:
                if retry_authentication:
                    print("Retrying and refreshing the token")
                    self.authorization_header = self.get_authorization_header(self.client_id,self.client_secret)
                else: 
                    return {
                        'status' : 'Authorization Fail',
                        'status_code' : response.status_code,
                        'response' : response
                    }
                    
            elif response.status_code >= 400:
                return {
                    'status' : 'Authorization Fail or Server Error',
                    'status_code' : response.status_code,
                    'response' : response
                }
            else:
                return {
                    'status' : 'Some Other Error',
                    'status_code' : response.status_code,
                    'response' : response
                }
            
    def get_authorization_key(self,client_id, client_secret):
        response = requests.post(
            'https://outpost.mappls.com/api/security/oauth/token',
            data={
                'grant_type':'client_credentials',
                'client_id':client_id,
                'client_secret':client_secret 
            }
        )
        resp_json=response.json()
        return f"{resp_json.get('token_type')} {resp_json.get('access_token')}"
    
    def get_authorization_header(self,client_id, client_secret):
        return {
            'Authorization' : self.get_authorization_key(client_id=client_id,client_secret=client_secret)
        }  
        
    def get_coordinates_from_eLoc(self,eloc):
        headers = headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Cookie": "_d3=eff5c0e04d082d2886173764eb5c26a3; _d4=eff5c0e04d082d2886173764eb5c26a3; PHPSESSID=c8i2en9qf2cbjv2mijrfuf2qa8; _autologin=aXNoYbmpW4xMzA4MDNfMTcyNTE3NjE4My05NGRhYTcyNDY5OGViMjI3LTEyOC4wLjAuMC1DaHJvbWUtNDQyOWFkZDYzNWZjMWEzODRmODY1MGQwYzFmZmU4NzU%3D",
            "Priority": "u=0, i",
            "Sec-CH-UA": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "Sec-CH-UA-Mobile": "?1",
            "Sec-CH-UA-Platform": '"Android"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
        }
        response = requests.get(f'https://www.mappls.com/{eloc}', headers=headers)
        if response.ok:
            soup = BeautifulSoup(response.content, 'html.parser')
            latitude = soup.find('input', {'id': 'lati'})
            longitude = soup.find('input', {'id' : 'longi'})
            d = {}
            if latitude and longitude:
                d['long'] = latitude.get('value')
                d['lat'] = longitude.get('value')
                return d
            else:
                raise Exception(f"Unable to retrieve the coordinates status_code : {response.status_code}")
        
            return response.json()
        else:
            raise Exception("Response is not ok")

    def get_geo_coded_data_with_coordinates(self,address):
        api_response = self.get_geo_coded_data(address=address)
        if api_response.get('status') != 'success':
            return api_response
        
        try:
            eloc = api_response['response']['eLoc']
            coordinate_data = self.get_coordinates_from_eLoc(eloc=eloc)
            api_response['response'].update(coordinate_data)
            return api_response
        except Exception as e:
            api_response['status'] = 'failed'
            api_response['exception'] = e
            return api_response
        
    def find_nearest_postoffices_distances(self,lat,long,limit = 5):
        lat = np.float64(lat)
        long = np.float64(long)
        target_coord = (lat,long)
        distance_2 = (self.df['Latitude'].to_numpy() - target_coord[0])**2 + (self.df['Longitude'].to_numpy() - target_coord[1])**2
        ser = pd.Series(np.sqrt(distance_2.astype(np.float64)))
        return ser.sort_values().head(limit)
        
    def get_nearest_postoffice(self,lat,long):
        lat = np.float64(lat)
        long = np.float64(long)
        target_coord = (lat,long)
        nearest_distances = self.find_nearest_postoffices_distances(lat,long)
        indices = nearest_distances.index.to_numpy()
        nearest_coordinates = self.df.loc[indices,['Latitude','Longitude']].to_numpy()
        origin = f"{lat},{long}"
        destinations = []
        for coords in nearest_coordinates:
            destinations.append(f"{coords[0]},{coords[1]}")
        destination_query = '|'.join(destinations)
        print(origin,destination_query)
        distance_matrix = self.ola_client.routing.distance_matrix(
            origin,
            destination_query
        )['rows'][0]['elements']
        newdf = pd.DataFrame(distance_matrix).sort_values(by="distance")
        ser = newdf.iloc[0]
        idx = int(ser.name)    
        coords = nearest_coordinates[idx]
        print(coords)
        data = ser.to_dict()
        data['lat'] = float(coords[0])
        data['long'] = float(coords[1])
        return data
    
    def get_geocoded_and_destination_coordinates(self, address):
        data = self.get_geo_coded_data_with_coordinates(address)
        
        source_lat = data['response']['long']
        source_long = data['response']['lat']
        destination_data = self.get_nearest_postoffice(source_lat,source_long)
        dest_lat = destination_data['lat']
        dest_long = destination_data['long']
                
        return {
            'receiver_lat':source_lat,
            'receiver_long':source_long,
            'post_lat':dest_lat,
            'post_long':dest_long,
            'pincode':data.get('response',{}).get('pincode'),
            'receiver_adddress' :data.get('response',{}).get('formattedAddress'),
            'post_address':None,
            'parsed_address':address,
        }
        
    def get_parse_address_from_image(self,url):
        response = self.gpt_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": url,
                        }
                        },
                        {
                            "type": "text",
                            "text": "The following image is of a letter , you need accurately identify only the reciever's address and return it to me . Your answer should consist of nothing but the reciever's address. If the address is not the reciever's address simply return not found"
                        }
                    ]
                }
            ],
            temperature=1,
            max_tokens=256,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            response_format={
                "type": "text"
            }
        )
        a=str(response.choices[0].message.content)
        return ', '.join(a.split('\n'))

    def get_parse_image_and_dest_coordinates(self,url):
        address = self.get_parse_address_from_image(url)
        coordinate_data = self.get_geocoded_and_destination_coordinates(address=address)
        return coordinate_data
       
       



class MMIServer:
    def __init__(self, mmi_client_id, mmi_client_secret, app_name = __name__):
        self.mmi = MMI(client_id=mmi_client_id, client_secret=mmi_client_secret)
        self.app = Flask(app_name)
        self.initialize_routes()
    
    def initialize_routes(self):
        @self.app.route('/')
        def hello():
            return "hello"
        
        @self.app.post('/api/v1/get-geocodes')
        def get_geocodes():
            address = urllib.parse.unquote(flask_request.args.get('address'))
            geocoded_data = self.mmi.get_geo_coded_data_with_coordinates(address=address)
            return geocoded_data
        
        @self.app.post('/api/v1/get-coords')
        def get_post_office_coords():
            address = urllib.parse.unquote(flask_request.args.get('address'))
            return jsonify(self.mmi.get_geocoded_and_destination_coordinates(
                address
            ))
        
        @self.app.post('/api/v1/parse-image')
        def parse_image_from_url():
            data = flask_request.get_json()
            img_url = data.get('url')
            if DUMMY_MODE.FLAG:
                return DUMMY_MODE.DUMMY_RESPONSE
            if img_url is None:
                return jsonify({'message' : 'Image url is None'}), 400
            return jsonify(self.mmi.get_parse_image_and_dest_coordinates(img_url))
            
        
            
    def get_app(self):
        return self.app
            
         
def main():
    mmiServer = MMIServer(CLIENT_ID, CLIENT_SECRET)
    app = mmiServer.get_app()
    url = 'https://loca.lt/mytunnelpassword'
    response = requests.get(url)
    for i in range(3):
        if response.status_code == 200:
            # Get the content of the response
            content = response.text
            print(f'Max tunnel password {content}')
            break
        else:
            print(f"Failed to retrieve the content Retrying after two seconds. Status code: {response.status_code}")
            time.sleep(10)
    else:
        raise Exception("Unable to fetch the tunnel password")
    CORS(app, resources={r"/*": {"origins": "*"}}, methods=['GET', 'POST', 'PUT','DELETE','UPDATE','OPTIONS'],supports_credentials=True, )
    command = ['lt', '--port', str(PORT), '--subdomain', SUBDOMAIN]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    app.run(port = PORT)
    
if __name__ == '__main__':
    main()