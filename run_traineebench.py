import json
from pathlib import Path
from typing import Union, List, Dict

from environment import Environment
from agent import Agent


def save_json(json_object: Union[List, Dict], save_to: str):
    with open(save_to, 'w', encoding='utf-8') as wf:
        json.dump(json_object, wf, ensure_ascii=False, indent=4)


scenario_path = Path(
    'benchmarks/traineebench/scenario_4kmtZc7e5NC2iAoTgNDsTG'
)
scenario_name = scenario_path.name
day_name = 'day_1'
day_path = scenario_path / day_name
bench_output_path = Path('outputs/traineebench')
log_path = bench_output_path / scenario_name / f'{day_name}.log'
messages_save_path = bench_output_path / scenario_name / f'{day_name}_messages.json'
evaluation_results_save_path = bench_output_path / scenario_name / f'{day_name}_evaluation.json'


env = Environment(
    tasks_path=day_path,
    log_level='INFO',
    log_path=log_path
)

agent = Agent(
    agent_name=env.ego_agent_names[0],
    model_name='gpt-4o'
)

agent.set_task_prompt(
    env.generate_tasks_prompt(agent.agent_name)
)

try:
    agent.forward(env, max_steps=50)
except Exception as e:
    raise e
finally:
    env.close()

    save_json(agent.messages, messages_save_path)

    evaluation_results = env.evaluate()
    evaluation_results['total_steps'] = {
        agent.agent_name: agent.step_count
    }
    save_json(evaluation_results, evaluation_results_save_path)
