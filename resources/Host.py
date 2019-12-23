import os
import tools.Resources
import resources.VirtualMachine


class Host:

    def __init__(self, target, name, uuid):
        self.target = target
        self.uuid = uuid
        self.name = name
        self.vms = list()

    def add_vm(self):
        project_ids = Resources.get_project_id(target=self.target)
        for vm in Resources.get_virtualmachines(target=self.target, parentid=self.uuid):
            if vm['uuid'] in project_ids:
                if os.environ['DEBUG'] == '1':
                    print(vm['name'] + ' has project id: ' + project_ids['project_id'])
                self.vms.append(VirtualMachine(name=vm['name'], uuid=vm['uuid'],
                                               project_id=project_ids['project_id']))
            else:
                self.vms.append(VirtualMachine(name=vm['name'], uuid=vm['uuid'],
                                               project_id='default internal'))
