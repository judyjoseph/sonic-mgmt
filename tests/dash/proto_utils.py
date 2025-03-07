import base64
import ipaddress
import re
import socket
import uuid
from ipaddress import ip_address

import pytest
from dash_api.acl_group_pb2 import AclGroup
from dash_api.acl_in_pb2 import AclIn
from dash_api.acl_out_pb2 import AclOut
from dash_api.acl_rule_pb2 import AclRule, Action
from dash_api.appliance_pb2 import Appliance
from dash_api.eni_pb2 import Eni, State
from dash_api.eni_route_pb2 import EniRoute
from dash_api.prefix_tag_pb2 import PrefixTag
from dash_api.qos_pb2 import Qos
from dash_api.route_group_pb2 import RouteGroup
from dash_api.route_pb2 import Route
from dash_api.route_rule_pb2 import RouteRule
from dash_api.route_type_pb2 import (ActionType, RouteType, RouteTypeItem,
                                     RoutingType)
from dash_api.types_pb2 import IpPrefix, IpVersion, ValueOrRange
from dash_api.vnet_mapping_pb2 import VnetMapping
from dash_api.vnet_pb2 import Vnet
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import ParseDict

ENABLE_PROTO = True

PB_INT_TYPES = set([
    FieldDescriptor.TYPE_INT32,
    FieldDescriptor.TYPE_INT64,
    FieldDescriptor.TYPE_UINT32,
    FieldDescriptor.TYPE_UINT64,
    FieldDescriptor.TYPE_FIXED64,
    FieldDescriptor.TYPE_FIXED32,
    FieldDescriptor.TYPE_SFIXED32,
    FieldDescriptor.TYPE_SFIXED64,
    FieldDescriptor.TYPE_SINT32,
    FieldDescriptor.TYPE_SINT64
])

PB_CLASS_MAP = {
    "APPLIANCE": Appliance,
    "VNET": Vnet,
    "ENI": Eni,
    "VNET_MAPPING": VnetMapping,
    "ROUTE": Route,
    "ROUTING_TYPE": RouteType,
    "ROUTE_GROUP": RouteGroup,
    "ENI_ROUTE": EniRoute,
}


def parse_ip_address(ip_str):
    ip_addr = ip_address(ip_str)
    if ip_addr.version == 4:
        encoded_val = socket.htonl(int(ip_addr))
    else:
        encoded_val = base64.b64encode(ip_addr.packed)

    return {f"ipv{ip_addr.version}": encoded_val}


def parse_ip_prefix(ip_prefix_str):
    ip_addr, mask = ip_prefix_str.split("/")
    return {"ip": parse_ip_address(ip_addr), "mask": parse_ip_address(ip_address(mask))}


def parse_byte_field(orig_val):
    return base64.b64encode(bytes.fromhex(orig_val.replace(":", "")))


def parse_guid(guid_str):
    return {"value": parse_byte_field(uuid.UUID(guid_str).hex)}


def parse_dash_proto(key: str, proto_dict: dict):
    """
    Custom parser for DASH configs to allow writing configs
    in a more human-readable format
    """
    table_name = re.search(r"DASH_(\w+)_TABLE", key).group(1)
    message = PB_CLASS_MAP[table_name]()
    field_map = message.DESCRIPTOR.fields_by_name
    new_dict = {}
    for key, value in proto_dict.items():
        if field_map[key].type == field_map[key].TYPE_MESSAGE:

            if field_map[key].message_type.name == "IpAddress":
                new_dict[key] = parse_ip_address(value)
            elif field_map[key].message_type.name == "IpPrefix":
                new_dict[key] = parse_ip_prefix(value)
            elif field_map[key].message_type.name == "Guid":
                new_dict[key] = parse_guid(value)

        elif field_map[key].type == field_map[key].TYPE_BYTES:
            new_dict[key] = parse_byte_field(value)

        elif field_map[key].type in PB_INT_TYPES:
            new_dict[key] = int(value)

        if key not in new_dict:
            new_dict[key] = value

    return ParseDict(new_dict, message)


def appliance_from_json(json_obj):
    pb = Appliance()
    pb.sip.ipv4 = socket.htonl(int(ipaddress.IPv4Address(json_obj["sip"])))
    pb.vm_vni = int(json_obj["vm_vni"])
    return pb


def vnet_from_json(json_obj):
    pb = Vnet()
    pb.vni = int(json_obj["vni"])
    pb.guid.value = bytes.fromhex(uuid.UUID(json_obj["guid"]).hex)
    return pb


def vnet_mapping_from_json(json_obj):
    pb = VnetMapping()
    pb.action_type = RoutingType.ROUTING_TYPE_VNET_ENCAP
    pb.underlay_ip.ipv4 = socket.htonl(int(ipaddress.IPv4Address(json_obj["underlay_ip"])))
    pb.mac_address = bytes.fromhex(json_obj["mac_address"].replace(":", ""))
    pb.use_dst_vni = json_obj["use_dst_vni"] == "true"
    return pb


def qos_from_json(json_obj):
    pb = Qos()
    pb.qos_id = json_obj["qos_id"]
    pb.bw = int(json_obj["bw"])
    pb.cps = int(json_obj["cps"])
    pb.flows = int(json_obj["flows"])
    return pb


def eni_from_json(json_obj):
    pb = Eni()
    pb.eni_id = json_obj["eni_id"]
    pb.mac_address = bytes.fromhex(json_obj["mac_address"].replace(":", ""))
    pb.underlay_ip.ipv4 = socket.htonl(int(ipaddress.IPv4Address(json_obj["underlay_ip"])))
    pb.admin_state = State.STATE_ENABLED if json_obj["admin_state"] == "enabled" else State.STATE_DISABLED
    pb.vnet = json_obj["vnet"]
    pb.qos = json_obj["qos"]
    return pb


def route_from_json(json_obj):
    pb = Route()
    if json_obj["action_type"] == "vnet":
        pb.action_type = RoutingType.ROUTING_TYPE_VNET
        pb.vnet = json_obj["vnet"]
    elif json_obj["action_type"] == "vnet_direct":
        pb.action_type = RoutingType.ROUTING_TYPE_VNET_DIRECT
        pb.vnet_direct.vnet = json_obj["vnet"]
        pb.vnet_direct.overlay_ip.ipv4 = socket.htonl(int(ipaddress.IPv4Address(json_obj["overlay_ip"])))
    elif json_obj["action_type"] == "direct":
        pb.action_type = RoutingType.ROUTING_TYPE_DIRECT
    else:
        pytest.fail("Unknown action type %s" % json_obj["action_type"])
    return pb


def route_rule_from_json(json_obj):
    pb = RouteRule()
    pb.action_type = RoutingType.ROUTING_TYPE_VNET_ENCAP
    pb.priority = int(json_obj["priority"])
    pb.pa_validation = json_obj["pa_validation"] == "true"
    if json_obj["pa_validation"] == "true":
        pb.vnet = json_obj["vnet"]
    return pb


def routing_type_from_json(json_obj):
    pb = RouteType()
    pbi = RouteTypeItem()
    pbi.action_name = json_obj["name"]
    pbi.action_type = ActionType.ACTION_TYPE_MAPROUTING
    pb.items.append(pbi)
    return pb


def acl_group_from_json(json_obj):
    pb = AclGroup()
    pb.guid.value = bytes.fromhex(uuid.UUID(json_obj["guid"]).hex)
    pb.ip_version = IpVersion.IP_VERSION_IPV4
    return pb


def acl_out_from_json(json_obj):
    pb = AclOut()
    pb.v4_acl_group_id = json_obj["acl_group_id"]
    return pb


def acl_in_from_json(json_obj):
    pb = AclIn()
    pb.v4_acl_group_id = json_obj["acl_group_id"]
    return pb


def acl_rule_from_json(json_obj):
    pb = AclRule()
    pb.priority = int(json_obj["priority"])
    pb.action = Action.ACTION_DENY if json_obj["action"] == "deny" else Action.ACTION_PERMIT
    pb.terminating = json_obj["terminating"] == "true"
    if "src_addr" in json_obj:
        for addr in json_obj["src_addr"].split(','):
            net = ipaddress.IPv4Network(addr, False)
            ip = IpPrefix()
            ip.ip.ipv4 = socket.htonl(int(net.network_address))
            ip.mask.ipv4 = socket.htonl(int(net.netmask))
            pb.src_addr.append(ip)
    if "dst_addr" in json_obj:
        for addr in json_obj["dst_addr"].split(','):
            net = ipaddress.IPv4Network(addr, False)
            ip = IpPrefix()
            ip.ip.ipv4 = socket.htonl(int(net.network_address))
            ip.mask.ipv4 = socket.htonl(int(net.netmask))
            pb.dst_addr.append(ip)
    if "src_port" in json_obj:
        for port in json_obj["src_port"].split(','):
            vr = ValueOrRange()
            if "-" not in port:
                vr.value = int(port)
            else:
                vr.range.min = int(port.split('-')[0])
                vr.range.max = int(port.split('-')[1])
            pb.src_port.append(vr)
    if "dst_port" in json_obj:
        for port in json_obj["dst_port"].split(','):
            vr = ValueOrRange()
            if "-" not in port:
                vr.value = int(port)
            else:
                vr.range.min = int(port.split('-')[0])
                vr.range.max = int(port.split('-')[1])
            pb.dst_port.append(vr)
    if "protocol" in json_obj:
        for proto in json_obj["protocol"].split(','):
            pb.protocol.append(int(proto))
    if "src_tag" in json_obj:
        for tag in json_obj["src_tag"].split(','):
            pb.src_tag.append(tag)
    if "dst_tag" in json_obj:
        for tag in json_obj["dst_tag"].split(','):
            pb.dst_tag.append(tag)
    return pb


def prefix_tag_from_json(json_obj):
    pb = PrefixTag()
    pb.ip_version = IpVersion.IP_VERSION_IPV4
    for ip_prefix in json_obj["prefix_list"].split(','):
        net = ipaddress.IPv4Network(ip_prefix, False)
        ip = IpPrefix()
        ip.ip.ipv4 = socket.htonl(int(net.network_address))
        ip.mask.ipv4 = socket.htonl(int(net.netmask))
        pb.prefix_list.append(ip)
    return pb


handlers_map = {
    "APPLIANCE": appliance_from_json,
    "VNET": vnet_from_json,
    "VNET_MAPPING": vnet_mapping_from_json,
    "QOS": qos_from_json,
    "ENI": eni_from_json,
    "ROUTE": route_from_json,
    "ROUTE_RULE": route_rule_from_json,
    "ROUTING_TYPE": routing_type_from_json,
    "ACL_GROUP": acl_group_from_json,
    "ACL_OUT": acl_out_from_json,
    "ACL_IN": acl_in_from_json,
    "ACL_RULE": acl_rule_from_json,
    "PREFIX_TAG": prefix_tag_from_json,
}


def json_to_proto(key, json_obj):
    table_name = re.search(r"DASH_(\w+)_TABLE", key).group(1)
    if table_name in handlers_map:
        pb = handlers_map[table_name](json_obj)
    else:
        pytest.fail("Unknown table %s" % table_name)
    return pb.SerializeToString()
