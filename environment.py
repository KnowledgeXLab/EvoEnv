import os
import sys
import json
import math
from loguru import logger
from typing import List, Dict, Any, Union
from datetime import datetime, timedelta
from collections import defaultdict

from tools_parser import ToolManager
from environments.traineebench.schemas.registry import call_evaluator
from virtual_server.registry import create_server
from virtual_server.base_server import BaseServer


class VirtualClock:
    def __init__(self, clock_config: Dict):
        self.action_costs: Dict[str, int] = clock_config['action_costs']
        start_str = clock_config.get("start_datetime")
        if start_str:
            try:
                self.now_dt = datetime.fromisoformat(start_str)
            except Exception:
                self.now_dt = datetime.now()
        else:
            self.now_dt = datetime.now()
        self.time_scale = clock_config.get("time_scale", 1)

    def now_str(self, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return self.now_dt.strftime(fmt)

    def advance_minutes(self, minutes: float):
        """
        Advance simulated clock by minutes, applying scale and ceil to integer minutes.

        Rules:
        - Apply global time_scale
        - Ceil to integer minutes
        - Enforce minimum of 1 minute for any positive cost
        """
        try:
            scaled = minutes * self.time_scale
            # ceil to int minutes; allow zero only if base is 0
            if scaled > 0:
                quantized = max(1, int(math.ceil(scaled)))
            else:
                quantized = 0
            if quantized > 0:
                delta = timedelta(minutes=quantized)
                self.now_dt = self.now_dt + delta
        except Exception:
            pass

    def advance_tool_call(self, tool_name: str):
        tool_cost = self.action_costs.get(tool_name, 1)*self.time_scale
        self.advance_minutes(tool_cost)


def setup_logging(level: str = "INFO", log_path: str = ''):
    logger.remove()

    logger.add(
        sys.stdout,
        level=level,

        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "{level} | "
               "<cyan>{name}</cyan>\n"
               "{message}\n",
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    if log_path:
        try:
            logger.add(
                log_path,
                level=level,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}\n{message}\n",
                rotation="100 MB",
                retention="7 days",
                compression="zip",
                enqueue=True,
                serialize=False,
            )
        except (ValueError, OSError) as e:
            logger.error(f"Failed to configure file logger at path '{log_path}': {e}")


class Environment:
    def __init__(
            self, task_path: str, log_level: str = 'INFO', log_path: str = ''
        ) -> None:
        self.task_root_path = task_path
        self.workspace = os.path.join(task_path, 'workspace')
        config_file = os.path.join(task_path, 'config.json')
        with open(config_file, 'r', encoding='utf-8') as rf:
            config: Dict = json.load(rf)

        self.log_path = log_path
        setup_logging(log_level, log_path)

        self.tasks: List[Dict] = config['tasks']

        clock_config = config.get('clock_config', None)
        if clock_config:
            self.clock = VirtualClock(clock_config)
        else:
            self.clock = None

        agents_config: Dict[str, List[Dict[str, Union[str, Dict]]]] = config['agents']
        self.agents_config = agents_config
        self.ego_agent_names = [
            ac['agent_name'] for ac in agents_config['ego_agents']
        ]

        tools_config: List[Dict] = config['tools']
        self.servers: Dict[str, BaseServer] = {}
        self.register_tools(tools_config)

        self.total_tool_calls: Dict[str, int] = defaultdict(int)

    def register_tools(self, tools_config: List[Dict]):
        tool_names = []
        server_names = []
        for tc in tools_config:
            tool_names.append(tc.get('name'))
            server_names += tc.get('dependency', None)

        for sd in server_names:
            self.servers[sd] = create_server(
                sd, 
                task_root_path = self.task_root_path,
                clock = self.clock,
                agents_config = self.agents_config
            )
        
        self.tool_manager = ToolManager(self.servers)
        self.tool_manager.load_tools(modules=tool_names)

    def generate_tasks_prompt(self, agent_name: str) -> str:
        system_prompt = ''
        for ego_agent in self.agents_config['ego_agents']:
            if ego_agent['agent_name'] == agent_name:
                system_prompt += ego_agent.get('system_prompt', None)

        if system_prompt:
            system_prompt += '\n\n'
        if self.tasks:
            system_prompt += f"Hi, {agent_name.split(' ')[0]} there's some work that needs your help:\n"
            for task_id, task in enumerate(self.tasks):
                task_name = task.get('task_name', '')
                task_description = task.get('task_description')
                deadline = task.get('deadline', '')
                if deadline:
                    system_prompt += f"\n## Task {task_id+1}-{task_name}\n\n{task_description}\nYou should finish this work before **{deadline}**.\n\n"
                else:
                    system_prompt += f"## Task {task_id+1}\n{task_description}\n\n"

        return system_prompt

    
    def execute_tool_calls(
            self, agent_name: str, tool_calls: List[Any]
        ) -> List[Dict[str, Any]]:
        execute_results = []
        if tool_calls:
            tool_call_info = f'[{agent_name}] Tool Calls:\n\n'
            for tc in tool_calls:
                try:
                    tc_args = json.loads(tc.function.arguments)
                except Exception as e:
                    tc_args = None

                if tc_args:
                    try:
                        tc_result = self.tool_manager.tools[tc.function.name](**tc_args)
                    except Exception as e:
                        tc_result = f'[Error] The following error occurred when you called the tool `{tc.function.name}`: {e.__str__()}.'
                else:
                    tc_result = f'[Error] There is a problem with the tool parameters you entered. Please make sure you enter the correct parameters in the correct format.'
                tool_call_info += f'ID: {tc.id}\n'
                tool_call_info += f'Tool Name: {tc.function.name}()\n'
                tool_call_info += f'Arguments: {tc.function.arguments}\n'
                if isinstance(tc_result, dict):
                    tool_call_info += f'Execute Results:\n{json.dumps(tc_result, ensure_ascii=False, indent=4)}\n\n'
                else:
                    tool_call_info += f'Execute Results:\n{tc_result}\n\n'

                attach_user_message = None
                if isinstance(tc_result, dict) and 'attach_user_message' in tc_result:
                    attach_user_message = tc_result.get('attach_user_message')
                    tool_call_result_str = json.dumps({"attach_user_message": True}, ensure_ascii=False)
                else:
                    tool_call_result_str = json.dumps(tc_result, ensure_ascii=False)

                execute_results.append(
                    {
                        'role': 'tool',
                        'name': tc.function.name,
                        'content': tool_call_result_str,
                        'tool_call_id': tc.id
                    }
                )
                if attach_user_message:
                    execute_results.append(
                        {
                            'role': 'user',
                            'content': attach_user_message
                        }
                    )
                if self.clock:
                    self.clock.advance_tool_call(tc.function.name)
                
                self.total_tool_calls[agent_name] += 1

            logger.info(tool_call_info)

        if self.clock:
            time_message = f'[System Time] Current time is {self.clock.now_str()}.'
            logger.info(time_message)
            execute_results.append(
                {
                    "role": "system",
                    "content": time_message
                }
            )

        return execute_results
    

    def evaluate(self) -> Dict:
        evaluation_results = []
        for task in self.tasks:
            evaluation_config = task.get('evaluation', None)
            if evaluation_config:
                func_name, func_args = evaluation_config['name'], evaluation_config['args']
                result = call_evaluator(
                    name=func_name, 
                    task_root_path=self.task_root_path, 
                    workspace_path=self.workspace,
                    **func_args
                )
                evaluation_results.append(
                    {
                        "task_name": task.get('task_name', ""),
                        "total_score": result['total_score'],
                        "full_score": result['full_score'],
                        "notes": result['notes']
                    }
                )
                logger.info(f"Evaluation Reuslt for {task['task_name']}:\n{result}.")

        if self.log_path:
            logger.info(f"Task has been finished, check {self.log_path} for details.")
        else:
            logger.info('Task has been finished.')

        output = {
            "evaluation_results": evaluation_results, 
            "total_tool_calls": self.total_tool_calls
        }

        return output
    
    def close(self):
        for server in self.servers.values():
            server.close()