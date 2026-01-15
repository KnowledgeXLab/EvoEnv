# TraineeBench

**TraineeBench** is a dynamic evaluation framework designed to evolve MLLM agent benchmarking from static, laboratory-controlled tests to stochastic, production-oriented workplace scenarios. 
By simulating a "corporate internship," the benchmark subjects agents to a continuous stream of tasks with shifting priorities and deadlines. Unlike information-complete benchmarks, TraineeBench enforces **partial observability**, requiring agents to proactively explore and uncover latent clues through interaction.

### 🌟 Core Innovations
- **Dynamic Workflows**: Moves beyond static Q&A to simulate real-world task streams with changing requirements.
- **Partial Observability**: Agents must actively explore the environment to find necessary information.
- **Procedural Generation**: Decouples logical meta-task rules from randomized environment variables, enabling the generation of infinite, unique task instances.
- **Stress Testing**: Rigorously evaluates context-aware scheduling, robust decision-making, and strategic evolution.

## ⚙️ Configuration

Before generating the benchmark, you must configure the LLM API services.

1.  **Create the config file**:
    Create an `api_config.json` file in the project root.
    ```bash
    touch api_config.json
    ```

2.  **Populate the configuration**:
    Fill in your model details below. The top-level key (e.g., `"gpt-4o"`) acts as the **model alias** you will use in CLI commands.

    ```json
    {
        "gpt-4o-mini": {
            "model_name": "gpt-4o-mini",
            "api_key_var": "sk-your_api_key",
            "base_url": "https://your.api.provider/v1/",
            "proxy_url": false
        },
        "gpt-4o": {
            "model_name": "gpt-4o",
            "api_key_var": "sk-your_api_key",
            "base_url": "https://your.api.provider/v1/",
            "proxy_url": "http://your.proxy.url/"
        }
    }
    ```
    *   `model_name`: The actual model identifier required by the service provider.
    *   `api_key_var`: Your actual API key string.
    *   `proxy_url`: Set to `false` if not needed, or provide the proxy string.

## 🛠️ Benchmark Generation

Use the following command to procedurally generate benchmark instances based on your configuration.

```bash
uv run environments/traineebench/gen_bench_from_config.py \
--config-path environments/traineebench/traineebench_config.json \
--bench-path  benchmarks/traineebench \
--npc-model   gpt-4o-mini
```

**Parameters:**
- `--npc-model`: The alias of the model used to simulate NPCs (must match a key in `api_config.json`).

## 🚀 Running the Benchmark

Once generated, launch the benchmark evaluation harness:

```bash
uv run run_traineebench.py
```

## 🧩 Custom Benchmark

*Instructions for creating custom TraineeBench scenarios via configuration files will be added here.*

```

```