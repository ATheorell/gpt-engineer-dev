"""
Module for defining a simple agent that uses AI to manage code generation and improvement.

This module provides a class that represents an agent capable of initializing and improving
a codebase using AI. It handles interactions with the AI model, memory, and execution
environment to generate and refine code based on user prompts.

"""

import tempfile

from typing import Optional

from gpt_engineer.core.ai import AI
from gpt_engineer.core.base_agent import BaseAgent
from gpt_engineer.core.base_execution_env import BaseExecutionEnv
from gpt_engineer.core.base_memory import BaseMemory
from gpt_engineer.core.default.disk_execution_env import DiskExecutionEnv
from gpt_engineer.core.default.disk_memory import DiskMemory
from gpt_engineer.core.default.paths import (
    PREPROMPTS_PATH,
    memory_path,
    ENTRYPOINT_FILE,
)
from gpt_engineer.core.default.steps import gen_code, gen_entrypoint, improve
from gpt_engineer.core.files_dict import FilesDict
from gpt_engineer.core.preprompts_holder import PrepromptsHolder

MAX_SELF_HEAL_ATTEMPTS = 4


class BenchmarkAgent(BaseAgent):
    """
    An agent that uses AI to generate and improve code based on a given prompt.

    This agent is capable of initializing a codebase from a prompt and improving an existing
    codebase based on user input. It uses an AI model to generate and refine code, and it
    interacts with a repository and an execution environment to manage and execute the code.

    Attributes
    ----------
    memory : BaseMemory
        The memory interface where the code and related data are stored.
    execution_env : BaseExecutionEnv
        The execution environment in which the code is executed.
    ai : AI
        The AI model used for generating and improving code.
    preprompts_holder : PrepromptsHolder
        The holder for preprompt messages that guide the AI model.
    """

    def __init__(
        self,
        memory: BaseMemory,
        execution_env: BaseExecutionEnv,
        ai: AI = None,
        preprompts_holder: PrepromptsHolder = None,
    ):
        self.preprompts_holder = preprompts_holder or PrepromptsHolder(PREPROMPTS_PATH)
        self.memory = memory
        self.execution_env = execution_env
        self.ai = ai or AI()

    @classmethod
    def with_default_config(
        cls, path: str, ai: AI = None, preprompts_holder: PrepromptsHolder = None
    ):
        return cls(
            memory=DiskMemory(memory_path(path)),
            execution_env=DiskExecutionEnv(),
            ai=ai,
            preprompts_holder=preprompts_holder or PrepromptsHolder(PREPROMPTS_PATH),
        )

    def init(self, prompt: str) -> FilesDict:
        files_dict = gen_code(self.ai, prompt, self.memory, self.preprompts_holder)
        entrypoint = gen_entrypoint(
            self.ai, files_dict, self.memory, self.preprompts_holder
        )
        combined_dict = {**files_dict, **entrypoint}
        files_dict = FilesDict(combined_dict)
        return files_dict

    def improve(
        self,
        files_dict: FilesDict,
        prompt: str,
        execution_command: Optional[str] = None,
    ) -> FilesDict:
        files_dict = improve(
            self.ai, prompt, files_dict, self.memory, self.preprompts_holder
        )
        self.execution_env.upload(files_dict)
        entrypoint = gen_entrypoint(
            self.ai, files_dict, self.memory, self.preprompts_holder
        )
        combined_dict = {**files_dict, **entrypoint}
        files_dict = FilesDict(combined_dict)
        self.self_heal(files_dict)
        return files_dict

    def self_heal(self, files_dict: FilesDict) -> None:
        """Attempts to execute the code from the entrypoint and if it fails,
        sends the error output back to the AI with instructions to fix.
        This code will make `MAX_SELF_HEAL_ATTEMPTS` to try and fix the code
        before giving up.
        This makes the assuption that the previous step was `gen_entrypoint`,
        this code could work with `simple_gen`, or `gen_clarified_code` as well.
        """

        # step 1. execute the entrypoint
        log_path = dbs.workspace.path / "log.txt"

        attempts = 0
        messages = []

        while attempts < MAX_SELF_HEAL_ATTEMPTS:
            attempts += 1
            log_file = open(log_path, "w")  # wipe clean on every iteration
            timed_out = False

            s = self.execution_env.popen(files_dict[ENTRYPOINT_FILE])
            try:  # timeout if the process actually runs
                p.wait()
            except subprocess.TimeoutExpired:
                timed_out = True
                print("The process hit a timeout before exiting.")

            # get the result and output
            # step 2. if the return code not 0, package and send to the AI
            if "log.txt" in dbs.workspace:
                log = dbs.workspace["log.txt"]
            else:
                log = ""

            def all_tests_passed(log):
                if not "test session starts" in log:
                    return True
                test_part = log.split("test session starts")[1]
                if "ERROR" in test_part or "FAILED" in test_part:
                    return False
                return True

            if (
                (p.returncode != 0 and p.returncode != 2) or not all_tests_passed(log)
            ) and not timed_out:
                print("run.sh failed.  The log is:")
                print(log)

                # pack results in an AI prompt

                # Using the log from the previous step has all the code and
                # the gen_entrypoint prompt inside.
                if attempts < 1:
                    messages = AI.deserialize_messages(
                        dbs.logs[gen_entrypoint_enhanced.__name__]
                    )
                    messages.append(
                        ai.fuser(get_platform_info())
                    )  # add in OS and Py version

                # append the error message
                messages.append(ai.fuser(log))
                if p.returncode != 0:
                    new_prompt = (
                        "A program has been written, but it doesn't run. The failure messages are "
                        + log
                    )
                    dbs.input["prompt"] = new_prompt
                    improve_existing_code(ai, dbs)
                else:
                    # rewrite prompt file
                    new_prompt = (
                        "A program has been written, but it doesn't pass mandatory tests. Make modification to the software so that the tests pass. Never modify the tests. The failure messages are "
                        + log
                    )
                    dbs.input["prompt"] = new_prompt
                    improve_existing_code(ai, dbs)
                log_file.close()
            else:
                log_file.close()
                return messages

        return messages


def default_config_agent():
    """
    Creates an instance of SimpleAgent with default configuration.

    Returns
    -------
    SimpleAgent
        An instance of SimpleAgent with a temporary directory as its base path.
    """
    return BenchmarkAgent.with_default_config(tempfile.mkdtemp())
