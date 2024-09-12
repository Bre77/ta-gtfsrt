from __future__ import print_function
from builtins import str
import os
import time
import sys
import xml.dom.minidom, xml.sax.saxutils
import logging

from google.transit import gtfs_realtime_pb2
import requests

#set up logging suitable for splunkd comsumption
logging.root
logging.root.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(levelname)s %(message)s')
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logging.root.addHandler(handler)

SCHEME = """<scheme>
    <title>GTFS Real Time</title>
    <description>Parse General Transit Feed Specification Real Time data.</description>
    <use_external_validation>false</use_external_validation>
    <streaming_mode>xml</streaming_mode>

    <endpoint>
        <args>
            <arg name="feed">
                <title>URL</title>
                <description>The GTFS Real Time URL endpoint.</description>
                <data_type>string</data_type>
                <required_on_create>true</required_on_create>
            </arg>
            <arg name="auth">
                <title>Authorisation header</title>
                <description>The value for the Authorisation header, such as "apikey abc123"</description>
                <data_type>string</data_type>
                <required_on_create>false</required_on_create>
            </arg>
        </args>
    </endpoint>
</scheme>
"""

def validate_conf(config, key):
    if key not in config:
        raise Exception("Invalid configuration received from Splunk: key '%s' is missing." % key)

# Routine to get the value of an input
def get_config():
    config = {}

    try:
        # read everything from stdin
        config_str = sys.stdin.read()

        # parse the config XML
        doc = xml.dom.minidom.parseString(config_str)
        root = doc.documentElement
        conf_node = root.getElementsByTagName("configuration")[0]
        if conf_node:
            logging.debug("XML: found configuration")
            stanza = conf_node.getElementsByTagName("stanza")[0]
            if stanza:
                stanza_name = stanza.getAttribute("name")
                if stanza_name:
                    logging.debug("XML: found stanza " + stanza_name)
                    config["name"] = stanza_name

                    params = stanza.getElementsByTagName("param")
                    for param in params:
                        param_name = param.getAttribute("name")
                        logging.debug("XML: found param '%s'" % param_name)
                        if param_name and param.firstChild and \
                           param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                            data = param.firstChild.data
                            config[param_name] = data
                            logging.debug("XML: '%s' -> '%s'" % (param_name, data))

        checkpnt_node = root.getElementsByTagName("checkpoint_dir")[0]
        if checkpnt_node and checkpnt_node.firstChild and \
           checkpnt_node.firstChild.nodeType == checkpnt_node.firstChild.TEXT_NODE:
            config["checkpoint_dir"] = checkpnt_node.firstChild.data

        if not config:
            raise Exception("Invalid configuration received from Splunk.")

        validate_conf(config, "feed")

    except Exception as e:
        raise Exception("Error getting Splunk configuration via STDIN: %s" % str(e))

    return config

# Routine to index data
def run_script():
    config=get_config()

    headers={}
    if("auth" in config):
        headers['Authorization'] = config["auth"]

    checkpointfile = os.path.join(config["checkpoint_dir"], "".join(c for c in config["name"] if c.isalnum() or c in (' ','.','_')).rstrip())

    # Checkpoint
    try:
        lasttime = int(open(checkpointfile, "r").read() or 0)
    except:
        lasttime = 0

    # GTFS Data
    feed = gtfs_realtime_pb2.FeedMessage()
    response = requests.get(config["feed"], headers=headers)
    feed.ParseFromString(response.content)

    logging.debug("Using last checkpoint {}s ago, next checkpoint is {}s ago".format(round(time.time()-lasttime,1),round(time.time()-feed.header.timestamp,2)))

    print("<stream>")
    for entity in feed.entity:
        if entity.HasField('vehicle') and entity.vehicle.timestamp > lasttime:
            print("<event><time>{}</time><source>{}</source><sourcetype>gtfsrt:vehicle</sourcetype><data>id=\"{}\" lat={} lng={} status=\"{}\" route=\"{}\" trip=\"{}\"</data></event>".format(entity.vehicle.timestamp,config["feed"],entity.vehicle.vehicle.id, entity.vehicle.position.latitude,entity.vehicle.position.longitude, entity.vehicle.current_status, entity.vehicle.trip.route_id, entity.vehicle.trip.trip_id))
        if entity.HasField('trip_update') and entity.trip_update.timestamp > lasttime:
            for update in entity.trip_update.stop_time_update:
                print("<event><time>{}</time><source>{}</source><sourcetype>gtfsrt:tripupdate</sourcetype><data>trip=\"{}\" route=\"{}\" vehicle=\"{}\" sequence={} stop=\"{}\" arrival_delay={} arrival_time={} departure_delay={} departure_time={}</data></event>".format(entity.trip_update.timestamp,config["feed"],entity.trip_update.trip.trip_id,entity.trip_update.trip.route_id,entity.trip_update.vehicle.id,update.stop_sequence,update.stop_id,update.arrival.delay,update.arrival.time,update.departure.delay,update.departure.time))
        if entity.HasField('alert') and entity.alert.active_period.end > lasttime:
            print("<event><time>{}</time><source>{}</source><sourcetype>gtfsrt:alert</sourcetype><data>header=\"{}\" description=\"{}\" url=\"{}\"</data></event>".format(entity.alert.active_period.start,config["feed"],entity.alert.header_text,entity.alert.description_text,entity.alert.url))
    print("</stream>")
    open(checkpointfile, "w").write(str(feed.header.timestamp))

# Script must implement these args: scheme, validate-arguments
if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scheme":
            print(SCHEME)
        elif sys.argv[1] == "--validate-arguments":
            pass
        else:
            pass
    else:
        run_script()

    sys.exit(0)