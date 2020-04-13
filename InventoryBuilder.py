from flask import Flask
from flask import request
from flask import abort
from flask import jsonify
from gevent.pywsgi import WSGIServer
from threading import Thread
from resources.Vcenter import Vcenter
from tools.Resources import Resources
import time
import json
import os


class InventoryBuilder:
    def __init__(self, json, port):
        self.json = json
        self.vcenter_dict = dict()
        self.target_tokens = dict()
        self.iterated_inventory = dict()
        self.successful_iteration_list = [0]
        self.wsgi_address = '0.0.0.0'
        if 'LOOPBACK' in os.environ:
            if os.environ['LOOPBACK'] == '1':
                self.wsgi_address = '127.0.0.1'

        thread = Thread(target=self.run_rest_server)
        thread.start()

        self.query_inventory_permanent()

    def run_rest_server(self):
        collectors = []
        metrics = []

        app = Flask(__name__)
        print('serving /vrops_list on', str(self.port))

        @app.route('/vrops_list', methods=['GET'])
        def vrops_list():
            return json.dumps(list(map(lambda x: x.server_name, self.vrops_list)))

        print('serving /inventory on', str(self.port))

        @app.route('/vcenters/<int:iteration>', methods=['GET'])
        def vcenters(iteration):
            return self.iterated_inventory[str(iteration)]['vcenters']

        @app.route('/datacenters/<int:iteration>', methods=['GET'])
        def datacenters(iteration):
            return self.iterated_inventory[str(iteration)]['datacenters']

        @app.route('/clusters/<int:iteration>', methods=['GET'])
        def clusters(iteration):
            return self.iterated_inventory[str(iteration)]['clusters']

        @app.route('/hosts/<int:iteration>', methods=['GET'])
        def hosts(iteration):
            return self.iterated_inventory[str(iteration)]['hosts']

        @app.route('/datastores/<int:iteration>', methods=['GET'])
        def datastores(iteration):
            return self.iterated_inventory[str(iteration)]['datastores']

        @app.route('/vms/<int:iteration>', methods=['GET'])
        def vms(iteration):
            return self.iterated_inventory[str(iteration)]['vms']

        @app.route('/iteration', methods=['GET'])
        def iteration():
            return_iteration = self.successful_iteration_list[-1]
            return str(return_iteration)

        # debugging purpose
        @app.route('/iteration_store', methods=['GET'])
        def iteration_store():
            return_iteration = self.successful_iteration_list
            return(json.dumps(return_iteration))

        @app.route('/register', methods=['POST'])
        def post_registered_collectors():
            if not request.json:
                abort(400)
            collector = {
                'collector': request.json["collector"],
                'metrics': request.json["metric_names"]
            }
            collectors.append(collector)
            return jsonify({"collectors registered": collectors})

        @app.route('/register', methods=['GET'])
        def get_registered_collectors():
            return jsonify({"collectors registered": collectors})

        @app.route('/metrics', methods=['POST'])
        def collect_metric_names():
            if not request.json:
                abort(400)
            metric = {
                'metric_name': request.json['metric_name']
            }
            metrics.append(metric)
            return jsonify({"collector metrics names ": metrics})

        @app.route('/metrics', methods=['GET'])
        def get_metric_names():
            return jsonify({"metrics": metrics})

        @app.route('/metrics', methods=['DELETE'])
        def delete_metric_names():
            metrics.clear()
            return jsonify({"metrics": metrics})

        # FIXME: this could basically be the always active token list. no active token? refresh!
        @app.route('/target_tokens', methods=['GET'])
        def token():
            return json.dumps(self.target_tokens)

        try:
            if os.environ['DEBUG'] >= '2':
                WSGIServer((self.wsgi_address, self.port), app).serve_forever()
            else:
                WSGIServer((self.wsgi_address, self.port), app, log=None).serve_forever()
        except TypeError as e:
            print('Problem starting server, you might want to try LOOPBACK=0 or LOOPBACK=1')
            print('Current used options:', str(self.wsgi_address), 'on port', str(self.port))
            print(e)

    def get_vrops(self):
        with open(self.json) as json_file:
            netbox_json = json.load(json_file)
        vrops_list = list()
        for target in netbox_json:
            if target['labels']['job'] == "vrops":
                vrops = types.SimpleNamespace()
                vrops.server_name = target['labels']['server_name']
                vrops.username    = target['labels'].get('username', None)
                vrops.password    = target['labels'].get('password', None)
                vrops.auth_source = target['labels'].get('auth_source', None)
                vrops_list.append(vrops)
        self.vrops_list = vrops_list

    def query_inventory_permanent(self):
        # first iteration to fill is 1. while this is not ready,
        # curl to /iteration would still report 0 to wait for actual data
        self.iteration = 1
        while True:
            # get vrops targets every run in case we have new targets appearing
            self.get_vrops()
            if len(self.successful_iteration_list) > 3:
                iteration_to_be_deleted = self.successful_iteration_list.pop(0)
                # initial case, since 0 is never filled in iterated_inventory
                if iteration_to_be_deleted == 0:
                    continue
                self.iterated_inventory.pop(str(iteration_to_be_deleted))
                if os.environ['DEBUG'] >= '1':
                    print("deleting iteration", str(iteration_to_be_deleted))

            # initialize empty inventory per iteration
            self.iterated_inventory[str(self.iteration)] = dict()
            if os.environ['DEBUG'] >= '1':
                print("real run " + str(self.iteration))
            for vrops in self.vrops_list:
                if not self.query_vrops(vrops):
                    print("retrying connection to", vrops.server_name, "in next iteration", str(self.iteration + 1))
            self.get_vcenters()
            self.get_datacenters()
            self.get_clusters()
            self.get_hosts()
            self.get_datastores()
            self.get_vms()
            if len(self.iterated_inventory[str(self.iteration)]['vcenters']) > 0:
                self.successful_iteration_list.append(self.iteration)
            else:
                # immediately withdraw faulty inventory
                if os.environ['DEBUG'] >= '1':
                    print("withdrawing current iteration", self.iteration)
                self.iterated_inventory.pop(str(self.iteration))
            self.iteration += 1
            if os.environ['DEBUG'] >= '1':
                print("inventory relaxing before going to work again")
            time.sleep(1800)

    def query_vrops(self, vrops):
        if os.environ['DEBUG'] >= '1':
            print("querying " + vrops.server_name)
        token = Resources.get_token(target=vrops.server_name, user=vrops.username, password=vrops.password, auth_source=vrops.auth_source)
        if not token:
            return False
        self.target_tokens[vrops.server_name] = token
        vcenter = self.create_resource_objects(vrops.server_name, token)
        self.vcenter_dict[vrops.server_name] = vcenter
        return True

    def create_resource_objects(self, vrops, token):
        for adapter in Resources.get_adapter(target=vrops, token=token):
            if os.environ['DEBUG'] >= '2':
                print("Collecting vcenter: " + adapter['name'])
            vcenter = Vcenter(target=vrops, token=token, name=adapter['name'], uuid=adapter['uuid'])
            vcenter.add_datacenter()
            for dc_object in vcenter.datacenter:
                if os.environ['DEBUG'] >= '2':
                    print("Collecting Datacenter: " + dc_object.name)
                dc_object.add_cluster()
                for cl_object in dc_object.clusters:
                    if os.environ['DEBUG'] >= '2':
                        print("Collecting Cluster: " + cl_object.name)
                    cl_object.add_host()
                    for hs_object in cl_object.hosts:
                        if os.environ['DEBUG'] >= '2':
                            print("Collecting Host: " + hs_object.name)
                        hs_object.add_datastore()
                        for ds_object in hs_object.datastores:
                            if os.environ['DEBUG'] >= '2':
                                print("Collecting Datastore: " + ds_object.name)
                        hs_object.add_vm()
                        for vm_object in hs_object.vms:
                            if os.environ['DEBUG'] >= '2':
                                print("Collecting VM: " + vm_object.name)
            return vcenter

    def get_vcenters(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            tree[vcenter.uuid] = {
                    'uuid': vcenter.uuid,
                    'name': vcenter.name,
                    'target': vcenter.target,
                    'token': vcenter.token,
                    }
        self.iterated_inventory[str(self.iteration)]['vcenters'] = tree
        return tree

    def get_datacenters(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            for dc in vcenter.datacenter:
                tree[dc.name] = {
                        'uuid': dc.uuid,
                        'name': dc.name,
                        'parent_vcenter_uuid': vcenter.uuid,
                        'parent_vcenter_name': vcenter.name,
                        'target': dc.target,
                        'token': dc.token,
                        }
        self.iterated_inventory[str(self.iteration)]['datacenters'] = tree
        return tree

    def get_clusters(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    tree[cluster.uuid] = {
                            'uuid': cluster.uuid,
                            'name': cluster.name,
                            'parent_dc_uuid': dc.uuid,
                            'parent_dc_name': dc.name,
                            'vcenter': vcenter.name,
                            'target': cluster.target,
                            'token': cluster.token,
                            }
        self.iterated_inventory[str(self.iteration)]['clusters'] = tree
        return tree

    def get_hosts(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        tree[host.uuid] = {
                                'uuid': host.uuid,
                                'name': host.name,
                                'parent_cluster_uuid': cluster.uuid,
                                'parent_cluster_name': cluster.name,
                                'datacenter': dc.name,
                                'target': host.target,
                                'token': host.token,
                                }
        self.iterated_inventory[str(self.iteration)]['hosts'] = tree
        return tree

    def get_datastores(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        for ds in host.datastores:
                            tree[ds.uuid] = {
                                    'uuid': ds.uuid,
                                    'name': ds.name,
                                    'parent_host_uuid': host.uuid,
                                    'parent_host_name': host.name,
                                    'cluster': cluster.name,
                                    'datacenter': dc.name,
                                    'target': ds.target,
                                    'token': ds.token,
                                    }
        self.iterated_inventory[str(self.iteration)]['datastores'] = tree
        return tree

    def get_vms(self):
        tree = dict()
        for vcenter_entry in self.vcenter_dict:
            vcenter = self.vcenter_dict[vcenter_entry]
            for dc in vcenter.datacenter:
                for cluster in dc.clusters:
                    for host in cluster.hosts:
                        for vm in host.vms:
                            tree[vm.uuid] = {
                                    'uuid': vm.uuid,
                                    'name': vm.name,
                                    'project_id': vm.project_id,
                                    'parent_host_uuid': host.uuid,
                                    'parent_host_name': host.name,
                                    'cluster': cluster.name,
                                    'datacenter': dc.name,
                                    'target': vm.target,
                                    'token': vm.token,
                                    }
        self.iterated_inventory[str(self.iteration)]['vms'] = tree
        return tree
