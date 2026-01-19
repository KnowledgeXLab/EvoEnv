import importlib
import inspect
import os
import re
from typing import Callable, List, Union, get_origin, get_args, Dict, Any
import inspect
from rich import print


class ToolManager:
    def __init__(
            self, servers: Dict[str, Any]
        ):
        self.tools = {}
        self.tools_schema = []

        self.servers = servers

    def register_tool(self, tool_name: str, tool_func: Callable):
        self.tools[tool_name] = tool_func

    def get_tool(self, tool_name: str):
        return self.tools.get(tool_name)
    
    def load_module_tools(self, tools_folder: str, module_name: str):
        try:
            module = importlib.import_module(f"{tools_folder}.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    callable(attr)
                    and not attr_name.startswith('_')
                    and getattr(attr, '__module__', None) == module.__name__
                ):
                    if inspect.isclass(attr):
                        try:
                            init_signature = inspect.signature(attr.__init__)

                            kwargs_to_pass = {}
                            
                            for param in init_signature.parameters.values():
                                if param.name == 'self':
                                    continue
                                
                                if param.name in self.servers:
                                    kwargs_to_pass[param.name] = self.servers[param.name]
                            
                            instantiated = attr(**kwargs_to_pass)
                        except Exception as e:
                            print(f"Error instantiating class '{attr_name}' from module '{module.__name__}': {e}")
                            continue
                        
                        tool_obj = instantiated.__call__
                    else:
                        tool_obj = attr
                    if callable(tool_obj):
                        self.register_tool(attr_name, tool_obj)

        except Exception as e:
            print(f"Error loading module '{tools_folder}.{module_name}': {e}")


    def load_tools(self, tools_folder: str="toolbox", modules: List[str] = None):
        if modules is None:
            modules = [
                filename[:-3] for filename in os.listdir(tools_folder)
                if filename.endswith('.py') and filename != '__init__.py'
            ]
        for module_name in modules:
            self.load_module_tools(tools_folder, module_name)
        for k, v in self.tools.items():
            self.tools_schema.append(generate_tool_schema(k,v))


def generate_tool_schema(func_name: str, func: Callable, enhance_des: str | None = None) -> str:
    TYPE_MAPPING = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        list: "array",
        tuple: "array",
        dict: "object",
        type(None): "null"
    }

    doc = inspect.getdoc(func)
    signature = inspect.signature(func)

    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }

    param_descriptions = {}
    if doc:
        match = re.search(r"Args:\s*(.*?)(?=\s*(?:Returns:|$))", doc, re.DOTALL)
        if match:
            args_section = match.group(1)
            param_lines = args_section.strip().splitlines()
            for line in param_lines:
                param_match = re.match(r"\s*(\w+)\s*:\s*(.*?)\s*$", line.strip())
                if param_match:
                    param_name, param_desc = param_match.groups()
                    param_descriptions[param_name] = param_desc.strip()

    for param_name, param in signature.parameters.items():
        param_type = param.annotation
        if param_type == inspect._empty:
            param_type = str

        if get_origin(param_type) is Union:
            possible_types = get_args(param_type)
            param_info = {"oneOf": []}
            for possible_type in possible_types:
                if get_origin(possible_type) is list:
                    param_info["oneOf"].append({
                        "type": "array",
                        "items": {
                            "type": TYPE_MAPPING.get(get_args(possible_type)[0], "string")
                        }
                    })
                else:
                    param_info["oneOf"].append({"type": TYPE_MAPPING.get(possible_type, "string")})

        elif get_origin(param_type) is list:
            param_info = {
                "type": "array",
                "items": {
                    "type": TYPE_MAPPING.get(get_args(param_type)[0], "string")
                }
            }
        else:
            param_info = {"type": TYPE_MAPPING.get(param_type, "string")}

        if param_name in param_descriptions:
            param_info["description"] = param_descriptions[param_name]
        else:
            param_info["description"] = f"No parameter description for {param_name}."

        # if param.default != inspect._empty:
        #     param_info["default"] = param.default
        if param.default is not None and param.default != inspect._empty:
            param_info["default"] = param.default

        parameters["properties"][param_name] = param_info

        if param.default == inspect._empty:
            parameters["required"].append(param_name)

    if enhance_des is not None:
        func_des = enhance_des
    elif doc:
        # func_des = doc.split("\nArgs:")[0]
        func_des = doc.split("\nArgs:")[0].strip()
    else:
        func_des = f"No parameter description for {param_name}."

    tool_schema = {
        "type": "function",
        "function": {
            "name": func_name,
            "description": func_des,
            "parameters": parameters
        }
    }

    return tool_schema

def generate_tool_des(func: Callable) -> str:
    doc = inspect.getdoc(func)

    if doc:
        match = re.split(r"\n\s*Args:\s*", doc, maxsplit=1)
        func_des = match[0].strip() if match else doc.strip()
    else:
        func_des = "No function description."

    return func_des


# if __name__ == '__main__':
#     import json

#     os_config = {
#         "action_costs": []
#     }

    # try:
    #     sandbox=DockerSandbox('./sandbox_workspace')
    #     scenario_clock = ScenarioClock(os_config)
    #     tool_manager = ToolManager(
    #         chat_server=ChatServer(),
    #         cloud_disk=CloudDisk('./CloudDisk', './sandbox_workspace'),
    #         sandbox=sandbox,
    #         meeting_calendar=MeetingRoomCalendar(
    #             'sandbox_workspace/meeting_calendar.db', scenario_clock
    #         )
    #     )
    #     tool_manager.load_tools(
    #         tools_folder='toolbox',
    #         modules=[
    #             'sandbox_tool', 'message_tool', 
    #             'cloud_disk_tool', 'calendar_tool',
    #             'calculator_tool', 'website_monitor'
    #         ]
    #     )

    #     for elem in tool_manager.tools_schema:
    #         print(elem)
            
    # except Exception as e:
    #     raise e
    # finally:
    #     sandbox.close()
