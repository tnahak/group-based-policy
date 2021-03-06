# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import webob.exc

from neutron.api import extensions
from neutron import context
from neutron.db import api as db_api
from neutron.db import model_base
from neutron.openstack.common import uuidutils
from neutron.plugins.common import constants
from neutron.tests.unit.api import test_extensions
from neutron.tests.unit.db import test_db_base_plugin_v2
from oslo_utils import importutils

from gbpservice.neutron.db import servicechain_db as svcchain_db
from gbpservice.neutron.extensions import group_policy as gpolicy
from gbpservice.neutron.extensions import servicechain as service_chain
from gbpservice.neutron.tests.unit import common as cm
from gbpservice.neutron.tests.unit.db.grouppolicy import test_group_policy_db

JSON_FORMAT = 'json'


class ServiceChainDBTestBase(test_group_policy_db.ApiManagerMixin):
    resource_prefix_map = dict(
        (k, constants.COMMON_PREFIXES[constants.SERVICECHAIN])
        for k in service_chain.RESOURCE_ATTRIBUTE_MAP.keys())
    resource_prefix_map.update(dict(
        (k, constants.COMMON_PREFIXES[constants.GROUP_POLICY])
        for k in gpolicy.RESOURCE_ATTRIBUTE_MAP.keys()
    ))

    fmt = JSON_FORMAT

    def __getattr__(self, item):
        # Verify is an update of a proper GBP object

        def _is_sc_resource(plural):
            return plural in service_chain.RESOURCE_ATTRIBUTE_MAP

        def _is_gbp_resource(plural):
            return plural in gpolicy.RESOURCE_ATTRIBUTE_MAP

        def _is_valid_resource(plural):
            return _is_gbp_resource(plural) or _is_sc_resource(plural)
        # Update Method
        if item.startswith('update_'):
            resource = item[len('update_'):]
            plural = cm.get_resource_plural(resource)
            if _is_valid_resource(plural):
                def update_wrapper(id, **kwargs):
                    return self._update_resource(id, resource, **kwargs)
                return update_wrapper
        # Show Method
        if item.startswith('show_'):
            resource = item[len('show_'):]
            plural = cm.get_resource_plural(resource)
            if _is_valid_resource(plural):
                def show_wrapper(id, **kwargs):
                    return self._show_resource(id, plural, **kwargs)
                return show_wrapper
        # Create Method
        if item.startswith('create_'):
            resource = item[len('create_'):]
            plural = cm.get_resource_plural(resource)
            if _is_valid_resource(plural):
                def create_wrapper(**kwargs):
                    return self._create_resource(resource, **kwargs)
                return create_wrapper
        # Delete Method
        if item.startswith('delete_'):
            resource = item[len('delete_'):]
            plural = cm.get_resource_plural(resource)
            if _is_valid_resource(plural):
                def delete_wrapper(id, **kwargs):
                    return self._delete_resource(id, plural, **kwargs)
                return delete_wrapper

        raise AttributeError

    def _get_resource_plural(self, resource):
        if resource.endswith('y'):
            resource_plural = resource.replace('y', 'ies')
        else:
            resource_plural = resource + 's'

        return resource_plural

    def _test_list_resources(self, resource, items,
                             neutron_context=None,
                             query_params=None):
        resource_plural = self._get_resource_plural(resource)

        res = self._list(resource_plural,
                         neutron_context=neutron_context,
                         query_params=query_params)
        params = query_params.split('&')
        params = dict((x.split('=')[0], x.split('=')[1].split(','))
                      for x in params)
        count = getattr(self.plugin, 'get_%s_count' % resource_plural)(
            neutron_context or context.get_admin_context(), params)
        self.assertEqual(len(res[resource_plural]), count)
        resource = resource.replace('-', '_')
        self.assertEqual(sorted([i['id'] for i in res[resource_plural]]),
                         sorted([i[resource]['id'] for i in items]))

    def _create_profiled_servicechain_node(
            self, service_type=constants.LOADBALANCER, shared_profile=False,
            profile_tenant_id=None, **kwargs):
        prof = self.create_service_profile(
            service_type=service_type,
            shared=shared_profile,
            tenant_id=profile_tenant_id or self._tenant_id)['service_profile']
        return self.create_servicechain_node(
            service_profile_id=prof['id'], **kwargs)


class ServiceChainDBTestPlugin(svcchain_db.ServiceChainDbPlugin):

        supported_extension_aliases = ['servicechain']


DB_GP_PLUGIN_KLASS = (ServiceChainDBTestPlugin.__module__ + '.' +
                      ServiceChainDBTestPlugin.__name__)

GP_PLUGIN_KLASS = (
    "gbpservice.neutron.services.grouppolicy.plugin.GroupPolicyPlugin")


class ServiceChainDbTestCase(ServiceChainDBTestBase,
                             test_db_base_plugin_v2.NeutronDbPluginV2TestCase):

    def setUp(self, core_plugin=None, sc_plugin=None, service_plugins=None,
              ext_mgr=None, gp_plugin=None):
        if not sc_plugin:
            sc_plugin = DB_GP_PLUGIN_KLASS
        if not service_plugins:
            service_plugins = {
                'l3_plugin_name': 'router',
                'gp_plugin_name': gp_plugin or GP_PLUGIN_KLASS,
                'sc_plugin_name': sc_plugin}

        super(ServiceChainDbTestCase, self).setUp(
            plugin=core_plugin, ext_mgr=ext_mgr,
            service_plugins=service_plugins
        )
        self.plugin = importutils.import_object(sc_plugin)
        if not ext_mgr:
            ext_mgr = extensions.PluginAwareExtensionManager.get_instance()
            self.ext_api = test_extensions.setup_extensions_middleware(ext_mgr)
        engine = db_api.get_engine()
        model_base.BASEV2.metadata.create_all(engine)

    def test_create_servicechain_specs_same_node(self):
        template1 = '{"key1":"value1"}'
        sp = self.create_service_profile(
            service_type=constants.FIREWALL)['service_profile']
        scn = self.create_servicechain_node(
            config=template1, service_profile_id=sp['id'])
        scn_id = scn['servicechain_node']['id']
        spec1 = {"servicechain_spec": {'name': 'scs1',
                                       'tenant_id': self._tenant_id,
                                       'nodes': [scn_id]}}
        spec_req = self.new_create_request('servicechain_specs',
                                           spec1,
                                           self.fmt)
        spec_res = spec_req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPCreated.code, spec_res.status_int)
        res = self.deserialize(self.fmt, spec_res)
        self.assertIn('servicechain_spec', res)
        self.assertEqual([scn_id], res['servicechain_spec']['nodes'])
        spec2 = {"servicechain_spec": {'name': 'scs2',
                                       'tenant_id': self._tenant_id,
                                       'nodes': [scn_id]}}
        spec_req = self.new_create_request('servicechain_specs',
                                           spec2,
                                           self.fmt)
        spec_res = spec_req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPCreated.code, spec_res.status_int)
        res = self.deserialize(self.fmt, spec_res)
        self.assertIn('servicechain_spec', res)
        self.assertEqual([scn_id], res['servicechain_spec']['nodes'])


class TestServiceChainResources(ServiceChainDbTestCase):

    def _test_show_resource(self, resource, resource_id, attrs):
        resource_plural = self._get_resource_plural(resource)
        req = self.new_show_request(resource_plural, resource_id,
                                    fmt=self.fmt)
        res = self.deserialize(self.fmt,
                               req.get_response(self.ext_api))

        for k, v in attrs.iteritems():
            self.assertEqual(v, res[resource][k])

    def test_create_and_show_servicechain_node(self):
        profile = self.create_service_profile(service_type=constants.FIREWALL)
        attrs = cm.get_create_servicechain_node_default_attrs(
            service_profile_id=profile['service_profile']['id'],
            config="config1")

        scn = self.create_servicechain_node(
            service_profile_id=profile['service_profile']['id'],
            config="config1")

        for k, v in attrs.iteritems():
            self.assertEqual(v, scn['servicechain_node'][k])

        self._test_show_resource('servicechain_node',
                                 scn['servicechain_node']['id'],
                                 attrs)

    def test_list_servicechain_nodes(self):
        scns = [
            self._create_profiled_servicechain_node(name='scn1',
                                                    description='scn'),
            self._create_profiled_servicechain_node(name='scn2',
                                                    description='scn'),
            self._create_profiled_servicechain_node(name='scn3',
                                                    description='scn')]
        self._test_list_resources('servicechain_node', scns,
                                  query_params='description=scn')

    def test_update_servicechain_node(self):
        name = 'new_servicechain_node'
        description = 'new desc'
        profile = self.create_service_profile(service_type=constants.FIREWALL)
        attrs = cm.get_create_servicechain_node_default_attrs(
            name=name, description=description,
            service_profile_id=profile['service_profile']['id'])

        scn = self.create_servicechain_node(
            service_profile_id=profile['service_profile']['id'])

        data = {'servicechain_node': {'name': name,
                                      'description': description}}
        req = self.new_update_request('servicechain_nodes', data,
                                      scn['servicechain_node']['id'])
        res = self.deserialize(self.fmt, req.get_response(self.ext_api))

        for k, v in attrs.iteritems():
            self.assertEqual(v, res['servicechain_node'][k])

        self._test_show_resource('servicechain_node',
                                 scn['servicechain_node']['id'],
                                 attrs)

    def test_delete_servicechain_node(self):
        ctx = context.get_admin_context()

        scn = self._create_profiled_servicechain_node()
        scn_id = scn['servicechain_node']['id']

        scs = self.create_servicechain_spec(nodes=[scn_id])
        scs_id = scs['servicechain_spec']['id']

        # Deleting Service Chain Node in use by a Spec should fail
        self.assertRaises(service_chain.ServiceChainNodeInUse,
                          self.plugin.delete_servicechain_node, ctx, scn_id)

        req = self.new_delete_request('servicechain_specs', scs_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)

        # After deleting the Service Chain Spec, node delete should succeed
        req = self.new_delete_request('servicechain_nodes', scn_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        self.assertRaises(service_chain.ServiceChainNodeNotFound,
                          self.plugin.get_servicechain_node,
                          ctx, scn_id)

    def test_create_and_show_servicechain_spec(self):
        name = "scs1"
        scn = self._create_profiled_servicechain_node()
        scn_id = scn['servicechain_node']['id']

        attrs = cm.get_create_servicechain_spec_default_attrs(
            name=name, nodes=[scn_id])

        scs = self.create_servicechain_spec(name=name, nodes=[scn_id])

        for k, v in attrs.iteritems():
            self.assertEqual(v, scs['servicechain_spec'][k])

        self._test_show_resource('servicechain_spec',
                                 scs['servicechain_spec']['id'],
                                 attrs)

    def test_create_spec_multiple_nodes(self):
        name = "scs1"
        scn1 = self._create_profiled_servicechain_node()
        scn1_id = scn1['servicechain_node']['id']
        scn2 = self._create_profiled_servicechain_node()
        scn2_id = scn2['servicechain_node']['id']
        attrs = cm.get_create_servicechain_spec_default_attrs(
            name=name, nodes=[scn1_id, scn2_id])
        scs = self.create_servicechain_spec(
            name=name, nodes=[scn1_id, scn2_id])
        for k, v in attrs.iteritems():
            self.assertEqual(v, scs['servicechain_spec'][k])

    def test_list_servicechain_specs(self):
        scs = [self.create_servicechain_spec(name='scs1', description='scs'),
               self.create_servicechain_spec(name='scs2', description='scs'),
               self.create_servicechain_spec(name='scs3', description='scs')]
        self._test_list_resources('servicechain_spec', scs,
                                  query_params='description=scs')

    def test_node_ordering_list_servicechain_specs(self):
        scn1_id = self._create_profiled_servicechain_node()[
            'servicechain_node']['id']
        scn2_id = self._create_profiled_servicechain_node()[
            'servicechain_node']['id']
        nodes_list = [scn1_id, scn2_id]
        scs = self.create_servicechain_spec(name='scs1',
                                            nodes=nodes_list)
        self.assertEqual(nodes_list, scs['servicechain_spec']['nodes'])
        res = self._list('servicechain_specs')
        self.assertEqual(1, len(res['servicechain_specs']))
        self.assertEqual(nodes_list, res['servicechain_specs'][0]['nodes'])

        # Delete the service chain spec and create another with nodes in
        # reverse order and verify that that proper ordering is maintained
        req = self.new_delete_request('servicechain_specs',
                                      scs['servicechain_spec']['id'])
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

        nodes_list.reverse()
        scs = self.create_servicechain_spec(name='scs1',
                                            nodes=nodes_list)
        self.assertEqual(scs['servicechain_spec']['nodes'], nodes_list)
        res = self._list('servicechain_specs')
        self.assertEqual(1, len(res['servicechain_specs']))
        self.assertEqual(nodes_list, res['servicechain_specs'][0]['nodes'])

    def test_update_servicechain_spec(self):
        name = "new_servicechain_spec1"
        description = 'new desc'
        scn_id = self._create_profiled_servicechain_node()[
            'servicechain_node']['id']
        attrs = cm.get_create_servicechain_spec_default_attrs(
            name=name, description=description, nodes=[scn_id])
        scs = self.create_servicechain_spec()
        data = {'servicechain_spec': {'name': name, 'description': description,
                                      'nodes': [scn_id]}}
        req = self.new_update_request('servicechain_specs', data,
                                      scs['servicechain_spec']['id'])
        res = self.deserialize(self.fmt, req.get_response(self.ext_api))

        for k, v in attrs.iteritems():
            self.assertEqual(v, res['servicechain_spec'][k])

        self._test_show_resource('servicechain_spec',
                                 scs['servicechain_spec']['id'], attrs)

    def test_delete_servicechain_spec(self):
        ctx = context.get_admin_context()

        scs = self.create_servicechain_spec()
        scs_id = scs['servicechain_spec']['id']

        req = self.new_delete_request('servicechain_specs', scs_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        self.assertRaises(service_chain.ServiceChainSpecNotFound,
                          self.plugin.get_servicechain_spec, ctx, scs_id)

    def test_delete_spec_in_use_by_policy_action_rejected(self):
        ctx = context.get_admin_context()
        scs_id = self.create_servicechain_spec()['servicechain_spec']['id']
        data = {'policy_action': {'action_type': 'redirect',
                                  'tenant_id': self._tenant_id,
                                  'action_value': scs_id}}
        pa_req = self.new_create_request('grouppolicy/policy_actions',
                                         data, self.fmt)
        res = pa_req.get_response(self.ext_api)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(code=res.status_int)

        self.assertRaises(service_chain.ServiceChainSpecInUse,
                          self.plugin.delete_servicechain_spec, ctx, scs_id)

    def test_delete_spec_in_use_by_instance_rejected(self):
        ctx = context.get_admin_context()
        scs_id = self.create_servicechain_spec()['servicechain_spec']['id']

        sci = self.create_servicechain_instance(servicechain_specs=[scs_id])
        sci_id = sci['servicechain_instance']['id']

        # Deleting the Spec used by Instance should not be allowed
        self.assertRaises(service_chain.ServiceChainSpecInUse,
                          self.plugin.delete_servicechain_spec, ctx, scs_id)

        req = self.new_delete_request('servicechain_instances', sci_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)
        self.assertRaises(service_chain.ServiceChainInstanceNotFound,
                          self.plugin.get_servicechain_instance,
                          ctx, sci_id)

        # Deleting the spec should succeed after the instance is deleted
        req = self.new_delete_request('servicechain_specs', scs_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)
        self.assertRaises(service_chain.ServiceChainSpecNotFound,
                          self.plugin.get_servicechain_spec, ctx, scs_id)

    def test_create_and_show_servicechain_instance(self):
        scs_id = self.create_servicechain_spec()['servicechain_spec']['id']
        policy_target_group_id = uuidutils.generate_uuid()
        classifier_id = uuidutils.generate_uuid()
        config_param_values = "{}"
        attrs = cm.get_create_servicechain_instance_default_attrs(
            servicechain_specs=[scs_id],
            provider_ptg_id=policy_target_group_id,
            consumer_ptg_id=policy_target_group_id,
            classifier_id=classifier_id,
            config_param_values=config_param_values)

        sci = self.create_servicechain_instance(
            servicechain_specs=[scs_id],
            provider_ptg_id=policy_target_group_id,
            consumer_ptg_id=policy_target_group_id,
            classifier_id=classifier_id,
            config_param_values=config_param_values)
        for k, v in attrs.iteritems():
            self.assertEqual(v, sci['servicechain_instance'][k])

        self._test_show_resource('servicechain_instance',
                                 sci['servicechain_instance']['id'],
                                 attrs)
        req = self.new_delete_request('servicechain_instances',
                                      sci['servicechain_instance']['id'])
        req.get_response(self.ext_api)

    def test_list_servicechain_instances(self):
        servicechain_instances = [self.create_servicechain_instance(
            name='sci1', description='sci'),
            self.create_servicechain_instance(name='sci2', description='sci'),
            self.create_servicechain_instance(name='sci3', description='sci')]
        self._test_list_resources('servicechain_instance',
                                  servicechain_instances,
                                  query_params='description=sci')

    def test_spec_ordering_list_servicechain_instances(self):
        scs1_id = self.create_servicechain_spec()['servicechain_spec']['id']
        scs2_id = self.create_servicechain_spec()['servicechain_spec']['id']
        specs_list = [scs1_id, scs2_id]
        sci = self.create_servicechain_instance(name='sci1',
                                                servicechain_specs=specs_list)
        self.assertEqual(specs_list,
                         sci['servicechain_instance']['servicechain_specs'])
        res = self._list('servicechain_instances')
        self.assertEqual(1, len(res['servicechain_instances']))
        result_instance = res['servicechain_instances'][0]
        self.assertEqual(specs_list, result_instance['servicechain_specs'])

        # Delete the service chain instance and create another with specs in
        # reverse order and verify that that proper ordering is maintained
        req = self.new_delete_request('servicechain_instances',
                                      sci['servicechain_instance']['id'])
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)

        specs_list.reverse()
        sci = self.create_servicechain_instance(name='sci1',
                                                servicechain_specs=specs_list)
        self.assertEqual(specs_list,
                         sci['servicechain_instance']['servicechain_specs'])
        res = self._list('servicechain_instances')
        self.assertEqual(1, len(res['servicechain_instances']))
        result_instance = res['servicechain_instances'][0]
        self.assertEqual(specs_list,
                         result_instance['servicechain_specs'])

    def test_update_servicechain_instance(self):
        name = "new_servicechain_instance"
        description = 'new desc'
        config_param_values = "{}"
        scs_id = self.create_servicechain_spec()['servicechain_spec']['id']
        provider_ptg_id = uuidutils.generate_uuid()
        consumer_ptg_id = uuidutils.generate_uuid()
        classifier_id = uuidutils.generate_uuid()
        attrs = cm.get_create_servicechain_instance_default_attrs(
            name=name, description=description, servicechain_specs=[scs_id],
            provider_ptg_id=provider_ptg_id, consumer_ptg_id=consumer_ptg_id,
            classifier_id=classifier_id,
            config_param_values=config_param_values)

        sci = self.create_servicechain_instance(
            servicechain_specs=[scs_id], provider_ptg_id=provider_ptg_id,
            consumer_ptg_id=consumer_ptg_id, classifier_id=classifier_id,
            config_param_values=config_param_values)
        data = {'servicechain_instance': {'name': name,
                                          'description': description,
                                          'servicechain_specs': [scs_id]}}
        req = self.new_update_request('servicechain_instances', data,
                                      sci['servicechain_instance']['id'])
        res = self.deserialize(self.fmt, req.get_response(self.ext_api))
        for k, v in attrs.iteritems():
            self.assertEqual(v, res['servicechain_instance'][k])

        self._test_show_resource('servicechain_instance',
                                 sci['servicechain_instance']['id'], attrs)
        req = self.new_delete_request('servicechain_instances',
                                      sci['servicechain_instance']['id'])
        req.get_response(self.ext_api)

    def test_delete_servicechain_instance(self):
        ctx = context.get_admin_context()

        sci = self.create_servicechain_instance()
        sci_id = sci['servicechain_instance']['id']

        req = self.new_delete_request('servicechain_instances', sci_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPNoContent.code, res.status_int)
        self.assertRaises(service_chain.ServiceChainInstanceNotFound,
                          self.plugin.get_servicechain_instance,
                          ctx, sci_id)

    def test_create_and_show_service_profile(self):
        attrs = cm.get_create_service_profile_default_attrs(
            service_type=constants.FIREWALL, vendor="vendor1")

        scn = self.create_service_profile(
            service_type=constants.FIREWALL, vendor="vendor1")

        for k, v in attrs.iteritems():
            self.assertEqual(scn['service_profile'][k], v)

        self._test_show_resource('service_profile',
                                 scn['service_profile']['id'], attrs)

    def test_list_service_profile(self):
        scns = [self.create_service_profile(name='sp1', description='sp',
                                            service_type='LOADBALANCER'),
                self.create_service_profile(name='sp2', description='sp',
                                            service_type='LOADBALANCER'),
                self.create_service_profile(name='sp3', description='sp',
                                            service_type='LOADBALANCER')]
        self._test_list_resources('service_profile', scns,
                                  query_params='description=sp')

    def test_update_service_profile(self):
        name = 'new_service_profile'
        description = 'new desc'
        attrs = cm.get_create_service_profile_default_attrs(
            name=name, description=description,
            service_type=constants.FIREWALL)

        scn = self.create_service_profile(service_type=constants.FIREWALL)

        data = {'service_profile': {'name': name,
                                    'description': description}}
        req = self.new_update_request('service_profiles', data,
                                      scn['service_profile']['id'])
        res = self.deserialize(self.fmt, req.get_response(self.ext_api))

        for k, v in attrs.iteritems():
            self.assertEqual(res['service_profile'][k], v)

        self._test_show_resource('service_profile',
                                 scn['service_profile']['id'], attrs)

    def test_delete_service_profile(self):
        ctx = context.get_admin_context()

        sp = self.create_service_profile(service_type='LOADBALANCER')
        sp_id = sp['service_profile']['id']

        scn = self.create_servicechain_node(service_profile_id=sp_id)
        scn_id = scn['servicechain_node']['id']

        # Deleting Service Chain Node in use by a Spec should fail
        self.assertRaises(service_chain.ServiceProfileInUse,
                          self.plugin.delete_service_profile, ctx, sp_id)

        req = self.new_delete_request('servicechain_nodes', scn_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)

        # After deleting the Service Chain Spec, node delete should succeed
        req = self.new_delete_request('service_profiles', sp_id)
        res = req.get_response(self.ext_api)
        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)
        self.assertRaises(service_chain.ServiceProfileNotFound,
                          self.plugin.get_service_profile,
                          ctx, sp_id)
