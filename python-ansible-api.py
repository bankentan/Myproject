#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
通过ansible API动态生成ansible资产信息但不产生实际的hosts文件
主机信息都可以通过数据库获得，然后生成指定格式，最后调用这个类来
生成主机信息。
"""

import sys
# 用于读取YAML和JSON格式的文件
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.parsing.dataloader import DataLoader
# 用于存储各类变量信息
from ansible.vars.manager import VariableManager
# 用于导入资产文件
from ansible.inventory.manager import InventoryManager
# 操作单个主机信息
from ansible.inventory.host import Host
# 操作单个主机组信息
from ansible.inventory.group import Group
# 状态回调，各种成功失败的状态
from ansible.plugins.callback import CallbackBase
from collections import namedtuple


class PlaybookCallResultCollector(CallbackBase):
    """
    playbook的callback改写，格式化输出playbook执行结果
    """
    CALLBACK_VERSION = 2.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.task_ok = {}
        self.task_unreachable = {}
        self.task_failed = {}
        self.task_skipped = {}
        self.task_status = {}

    def v2_runner_on_unreachable(self, result):
        """
        重写 unreachable 状态
        :param result:  这是父类里面一个对象，这个对象可以获取执行任务信息
        """
        self.task_unreachable[result._host.get_name()] = result

    def v2_runner_on_ok(self, result, *args, **kwargs):
        """
        重写 ok 状态
        :param result:
        """
        self.task_ok[result._host.get_name()] = result

    def v2_runner_on_failed(self, result, *args, **kwargs):
        """
        重写 failed 状态
        :param result:
        """
        self.task_failed[result._host.get_name()] = result

    def v2_runner_on_skipped(self, result):
        self.task_skipped[result._host.get_name()] = result

    # def v2_playbook_on_stats(self, stats):
    #     hosts = sorted(stats.processed.keys())
    #     for h in hosts:
    #         t = stats.summarize(h)
    #         self.task_status[h] = {
    #             "ok": t["ok"],
    #             "changed": t["changed"],
    #             "unreachable": t["unreachable"],
    #             "skipped": t["skipped"],
    #             "failed": t["failed"]
    #         }


class MyInventory:
    def __init__(self, hostsresource):
        """
        初始化函数
        :param hostsresource: 主机资源可以有2种形式
        列表形式: [{"ip": "172.16.48.171", "port": "22", "username": "root", "password": "123456"}]
        字典形式: {
                    "Group1": {
                        "hosts": [{"ip": "192.168.200.10", "port": "1314", "username": "root", "password": None}],
                        "vars": {"var1": "ansible"}
                    },
                    "Group2": {}
                }
        """
        self._hostsresource = hostsresource
        self._loader = DataLoader()
        self._hostsfilelist = ["temphosts"]
        """
        sources这个我们知道这里是设置hosts文件的地方，它可以是一个列表里面包含多个文件路径且文件真实存在，在单纯的执行ad-hoc的时候这里的
        文件里面必须具有有效的hosts配置，但是当通过动态生成的资产信息的时候这个文件必须存在但是它里面可以是空的，如果这里配置成None那么
        它不影响资产信息动态生成但是会有一个警告，所以还是要配置一个真实文件。
        """
        self._inventory = InventoryManager(loader=self._loader, sources=self._hostsfilelist)
        self._variable_manager = VariableManager(loader=self._loader, inventory=self._inventory)

        self._dynamic_inventory()

    def _add_dynamic_group(self, hosts_list, groupname, groupvars=None):
        """
        动态添加主机到指定的主机组

        完整的HOSTS文件格式
        [test1]
        hostname ansible_ssh_host=192.168.1.111 ansible_ssh_user="root" ansible_ssh_pass="123456"

        但通常我们都省略hostname，端口也省略因为默认是22，这个在ansible配置文件中有，除非有非22端口的才会配置
        [test1]
        192.168.100.10 ansible_ssh_user="root" ansible_ssh_pass="123456" ansible_python_interpreter="/PATH/python3/bin/python3"

        :param hosts_list: 主机列表 [{"ip": "192.168.100.10", "port": "22", "username": "root", "password": None}, {}]
        :param groupname:  组名称
        :param groupvars:  组变量，格式为字典
        :return:
        """
        # 添加组
        my_group = Group(name=groupname)
        self._inventory.add_group(groupname)

        # 添加组变量
        if groupvars:
            for key, value in groupvars.items():
                my_group.set_variable(key, value)

        # 添加一个主机
        for host in hosts_list:
            hostname = host.get("hostname", None)
            hostip = host.get("ip", None)
            if hostip is None:
                print("IP地址为空，跳过该元素。")
                continue
            hostport = host.get("port", "22")
            username = host.get("username", "root")
            password = host.get("password", None)
            ssh_key = host.get("ssh_key", None)
            python_interpreter = host.get("python_interpreter", None)

            try:
                # hostname可以不写，如果为空默认就是IP地址
                if hostname is None:
                    hostname = hostip
                # 生成一个host对象
                my_host = Host(name=hostname, port=hostport)
                # 添加主机变量
                self._variable_manager.set_host_variable(host=my_host, varname="ansible_ssh_host", value=hostip)
                self._variable_manager.set_host_variable(host=my_host, varname="ansible_ssh_port", value=hostport)
                if password:
                    self._variable_manager.set_host_variable(host=my_host, varname="ansible_ssh_pass", value=password)
                self._variable_manager.set_host_variable(host=my_host, varname="ansible_ssh_user", value=username)
                if ssh_key:
                    self._variable_manager.set_host_variable(host=my_host, varname="ansible_ssh_private_key_file", value=ssh_key)
                if python_interpreter:
                    self._variable_manager.set_host_variable(host=my_host, varname="ansible_python_interpreter", value=python_interpreter)

                # 添加其他变量
                for key, value in host.items():
                    if key not in ["ip", "hostname", "port", "username", "password", "ssh_key", "python_interpreter"]:
                        self._variable_manager.set_host_variable(host=my_host, varname=key, value=value)

                # 添加主机到组
                self._inventory.add_host(host=hostname, group=groupname, port=hostport)

            except Exception as err:
                print(err)

    def _dynamic_inventory(self):
        """
        添加 hosts 到inventory
        :return:
        """
        if isinstance(self._hostsresource, list):
            self._add_dynamic_group(self._hostsresource, "default_group")
        elif isinstance(self._hostsresource, dict):
            for groupname, hosts_and_vars in self._hostsresource.items():
                self._add_dynamic_group(hosts_and_vars.get("hosts"), groupname, hosts_and_vars.get("vars"))

    @property
    def INVENTORY(self):
        """
        返回资产实例
        :return:
        """
        return self._inventory

    @property
    def VARIABLE_MANAGER(self):
        """
        返回变量管理器实例
        :return:
        """
        return self._variable_manager


class AnsibleRunner(object):
    def __init__(self, hostsresource):
        Options = namedtuple("Options", [
            "connection", "remote_user", "ask_sudo_pass", "verbosity", "ack_pass",
            "module_path", "forks", "become", "become_method", "become_user", "check",
            "listhosts", "listtasks", "listtags", "syntax", "sudo_user", "sudo", "diff"
        ])
        self._options = Options(connection='smart', remote_user=None, ack_pass=None, sudo_user=None, forks=5, sudo=None,
                          ask_sudo_pass=False,
                          verbosity=5, module_path=None, become=None, become_method=None, become_user=None, check=False,
                          diff=False,
                          listhosts=None, listtasks=None, listtags=None, syntax=None)
        self._passwords = dict(sshpass=None, becomepass=None)  # 这个可以为空，因为在hosts文件中
        self._loader = DataLoader()
        myinven = MyInventory(hostsresource=hostsresource)
        self._inventory = myinven.INVENTORY
        self._variable_manager = myinven.VARIABLE_MANAGER

    def run_playbook(self, playbook_path, extra_vars=None):
        """
        执行playbook
        :param playbook_path: playbook的yaml文件路径
        :param extra_vars: 额外变量
        :return: 无返回值
        """
        try:
            if extra_vars:
                self._variable_manager.extra_vars = extra_vars
            playbook = PlaybookExecutor(playbooks=[playbook_path], inventory=self._inventory, variable_manager=self._variable_manager, loader=self._loader, passwords=self._passwords)
            # 配置使用自定义callback
            self._callback = PlaybookCallResultCollector()
            playbook._tqm._stdout_callback = self._callback
            # 执行playbook
            playbook.run()
        except Exception as err:
            print(err)

    def get_playbook_result(self):
        """
        获取playbook执行结果
        :return:
        """
        result_raw = {"ok": {}, "failed": {}, "unreachable": {}, "skipped": {}, "status": {}}
        for host, result in self._callback.task_ok.items():
            result_raw["ok"][host] = result._result

        for host, result in self._callback.task_failed.items():
            result_raw["failed"][host] = result._result

        for host, result in self._callback.task_unreachable.items():
            result_raw["unreachable"][host] = result._result

        for host, result in self._callback.task_skipped.items():
            result_raw["skipped"][host] = result._result

        for host, result in self._callback.task_status.items():
            result_raw["status"][host] = result._result

        return result_raw


def main():
    temphosts_list = [{"ip": "222.187.0.121", "port": "2121", "username": "root", "password": "/*bankentan123"}]

    temphosts_dict = {
        "Group1": {
            "hosts": [{"ip": "192.168.200.10", "port": "1314", "username": "root", "password": None}],
            "vars": {"var1": "ansible"}
        },
        # "Group2": {}
    }

    # mi = MyInventory(temphosts_list)
    # for group, hosts in mi.INVENTORY.get_groups_dict().items():
    #     print(group, hosts)
    # host = mi.INVENTORY.get_host("192.168.200.10")
    # print(mi.VARIABLE_MANAGER.get_vars(host=host))

    ar = AnsibleRunner(temphosts_list)
    ar.run_playbook("/root/ansible/test.yml")
    print(ar.get_playbook_result())

if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit()
