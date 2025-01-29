"""
🤖 F.l.a.t. (Frameworkless LLM Agent... Thing)! 🤖

Look, we get it. You're tired of AI libraries that are more complex than your ex's emotional baggage.
Enter FlatAI - the AI wrapper that's flatter than your first pancake attempt!

This bad boy wraps around OpenAI's API like a warm tortilla around your favorite burrito fillings,
making it easier to digest and way less likely to cause mental indigestion.

Key Features:
- 🎯 Simple: So simple, your rubber duck could probably use it
- 🔄 Retries: Because even AI needs a second chance (or three)
- 🧠 Context Management: Like a brain, but one you can actually control
- 🎲 Function Picking: Let AI choose your functions like your mom chooses your clothes
- 📝 Object Generation: Creates objects faster than your cat creates chaos
- 🔄 Logic Blocks: if/else, loops, switch cases - all the Python goodies you know and love
- 🎭 Dynamic Flow: Control your AI's behavior with familiar programming patterns

License: MIT (Because sharing is caring, and lawyers are expensive)

Author: Your Friendly Neighborhood AI Wrangler
"""

import json
import time
import traceback
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Type

import openai
from pydantic import BaseModel, Field

from flat_ai.function_helpers import (
    FunctionCall,
    FunctionsToCall,
    create_openai_function_description,
)
from flat_ai.trace_llm import MyOpenAI

openai.OpenAI = MyOpenAI


class FlatAI:
    def __init__(
        self,
        client: Optional[openai.OpenAI] = None,
        model: str = "gpt-4o-mini",
        retries: int = 3,
        base_url: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
    ):
        if client:
            self.client = client
        elif api_key:
            self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
        else:
            raise ValueError("Must provide either client or api_key")

        self.model = model
        self.retries = retries
        self._context = OrderedDict()
        self.base_url = base_url

    def _retry_on_error(self, func: Callable, *args, **kwargs) -> Any:
        """Helper method to retry operations on failure"""
        last_exception = None
        last_traceback = None
        for attempt in range(self.retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                last_traceback = traceback.format_exc()
                if attempt < self.retries - 1:
                    time.sleep(1 * (attempt + 1))  # Exponential backoff
                    continue
                raise Exception(
                    f"Operation failed after {self.retries} attempts. Last error: {str(last_exception)}\nTraceback:\n{last_traceback}"
                )

    def set_context(self, **kwargs):
        """Set the context for future LLM interactions"""
        self._context = OrderedDict(kwargs)

    def add_context(self, **kwargs):
        """Add additional context while preserving existing context"""
        self._context.update(kwargs)

    def clear_context(self):
        """Clear all context"""
        self._context = {}

    def delete_from_context(self, *keys):
        """Remove specific keys from context"""
        for key in keys:
            self._context.pop(key, None)

    def _parse_openai_kwargs(self, **kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Separate known OpenAI parameters from custom ones.
        Returns (openai_kwargs, custom_kwargs).
        """
        openai_param_names = {
            "model",
            "audio",
            "frequency_penalty",
            "function_call",
            "functions",
            "logit_bias",
            "logprobs",
            "max_completion_tokens",
            "max_tokens",
            "metadata",
            "modalities",
            "n",
            "parallel_tool_calls",
            "prediction",
            "presence_penalty",
            "reasoning_effort",
            "response_format",
            "seed",
            "service_tier",
            "stop",
            "store",
            "stream",
            "stream_options",
            "temperature",
            "tool_choice",
            "tools",
            "top_logprobs",
            "top_p",
            "user",
            "extra_headers",
            "extra_query",
            "extra_body",
            "timeout",
        }
        openai_kwargs = {}
        custom_kwargs = {}
        for key, value in kwargs.items():
            if key in openai_param_names:
                openai_kwargs[key] = value
            else:
                custom_kwargs[key] = value

        if "model" not in openai_kwargs.keys():
            openai_kwargs["model"] = self.model

        return openai_kwargs, custom_kwargs

    def _build_messages(self, *message_parts, **kwargs) -> List[Dict[str, str]]:
        """Build message list with context as system message if present"""
        messages = []

        context_dict = OrderedDict()
        # Add context items first in order
        if self._context:
            for key, value in self._context.items():
                if isinstance(value, BaseModel):
                    context_dict[key] = json.loads(value.model_dump_json())
                else:
                    context_dict[key] = str(value)

        # Add/override with kwargs items while maintaining order
        if kwargs:
            for key, value in kwargs.items():
                if value is None or value == "":
                    continue
                if isinstance(value, BaseModel):
                    context_dict[key] = json.loads(value.model_dump_json())
                else:
                    context_dict[key] = str(value)

        if context_dict:
            messages.append(
                {"role": "system", "content": json.dumps(context_dict, indent=2)}
            )

        messages.extend(message_parts)
        return messages

    def is_true(self, _question: str, **kwargs) -> bool:
        class IsItTrue(BaseModel):
            is_it_true: bool

        """Ask a yes/no question and get a boolean response"""
        ret = self.generate_object(IsItTrue, _question=_question, **kwargs)
        return ret.is_it_true

    def classify(self, options: Dict[str, str], **kwargs) -> str:
        """Get a key from provided options based on context"""

        class Classification(BaseModel):
            choice: str = Field(
                description=(
                    "Select exactly one of the following classification keys. "
                    "See 'classification_options' in the context for their meaning."
                ),
                enum=list(options.keys()),
            )

        def _execute():
            if not options:
                raise ValueError("Options dictionary cannot be empty")
            user_prompt = (
                "You are given a set of labeled options, each key having a descriptive meaning. "
                "Please analyze the context and choose exactly one of these keys:\n\n"
                + json.dumps(options, indent=2)
                + "\n\n"
                "Return your final choice of classification key in the 'choice' field."
            )

            result = self.generate_object(
                Classification, user_prompt=user_prompt, options=options, **kwargs
            )
            return result.choice

        return self._retry_on_error(_execute)

    def generate_object(
        self, schema_class: Type[BaseModel | List[BaseModel]], **kwargs
    ) -> Any:
        """Generate an object matching the provided schema"""

        # LIST OF Pydantic models
        class ObjectArray(BaseModel):
            items: (
                List[schema_class.__args__[0]]
                if hasattr(schema_class, "__origin__")
                and schema_class.__origin__ == list
                else List[schema_class]
            )

        # if its a list of Pydantic models, we need to create a new schema for the array
        if hasattr(schema_class, "__origin__") and schema_class.__origin__ == list:
            is_list = True
            schema_name = schema_class.__args__[0].__name__ + "Array"
            schema = ObjectArray.model_json_schema()
        # Handle Pydantic models
        else:
            is_list = False
            schema = schema_class.model_json_schema()
            schema_name = schema_class.__name__

        openai_kwargs, custom_kwargs = self._parse_openai_kwargs(**kwargs)

        messages = self._build_messages(
            {
                "role": "user",
                "content": "Based on the provided context and information, generate a complete and accurate object that precisely matches the schema. Use all relevant details to populate the fields with meaningful, appropriate values that best represent the data.",
            },
            **custom_kwargs,
        )

        def _execute():
            # if Fireworks or Together use a different response format
            if self.base_url in [
                "https://api.fireworks.ai/inference/v1",
                "https://api.together.xyz/v1",
            ]:
                openai_kwargs["response_format"] = {
                    "type": "json_object",
                    "schema": schema,
                }
            else:
                openai_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema},
                }

            openai_kwargs["messages"] = messages

            response = self.client.chat.completions.create(**openai_kwargs)

            result = json.loads(response.choices[0].message.content)

            # Handle list of Pydantic models
            if is_list:
                items = ObjectArray.model_validate(result).items
                return items
            # Handle single Pydantic model
            else:
                return schema_class.model_validate(result)

        return self._retry_on_error(_execute)

    def call_function(self, func: Callable, **kwargs) -> Any:
        """Call a function with AI-determined arguments"""
        func = self.pick_a_function([func], **kwargs)
        return func()

    def pick_a_function(
        self, functions: List[Callable], _multiple_functions=True, **kwargs
    ) -> FunctionsToCall:
        """Pick appropriate function and arguments based on instructions"""
        tool_choice = "required"
        if None in functions:
            tool_choice = "auto"
        functions = [f for f in functions if f is not None]

        tools = [create_openai_function_description(func) for func in functions]

        if _multiple_functions:
            instruction_message = "Based on all the provided context and information, analyze and select the most appropriate functions from the available options. Then, determine and specify the optimal parameters for each function to achieve the intended outcome."
        else:
            instruction_message = "Based on all the provided context and information, analyze and select the most appropriate function from the available options. Then, determine and specify the optimal parameters for that function to achieve the intended outcome."

        openai_kwargs, custom_kwargs = self._parse_openai_kwargs(**kwargs)
        messages = self._build_messages(
            {"role": "user", "content": instruction_message},
            **custom_kwargs,
        )

        def _execute():
            functions_to_call = FunctionsToCall()

            response = self.client.chat.completions.create(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **openai_kwargs,
            )

            # Process all tool calls if there are any
            tool_calls = response.choices[0].message.tool_calls or []
            content = response.choices[0].message.content

            if tool_calls == [] and tool_choice == "required" and content:
                raise Exception(
                    "No tools found"
                )  # This is an error that can be handled by the caller

            # If _multiple_functions is False, only process the first tool call
            if not _multiple_functions and len(tool_calls) > 0:
                tool_calls = [tool_calls[0]]

            for tool_call in tool_calls:
                if tool_choice == "auto" and tool_call.function.name == "None":
                    continue

                chosen_func = next(
                    f for f in functions if f.__name__ == tool_call.function.name
                )

                args = json.loads(tool_call.function.arguments, strict=False)
                # Convert string lists back to actual lists
                for key, value in args.items():
                    if (
                        isinstance(value, str)
                        and value.startswith("[")
                        and value.endswith("]")
                    ):
                        try:
                            args[key] = json.loads(value, strict=False)
                        except json.JSONDecodeError:
                            pass

                function_call = FunctionCall(function=chosen_func, arguments=args)
                functions_to_call.functions.append(function_call)

            return functions_to_call

        return self._retry_on_error(_execute)

    def get_string(self, prompt: str, **kwargs) -> str:
        """Get a simple string response from the LLM"""

        def _execute():
            openai_kwargs, custom_kwargs = self._parse_openai_kwargs(**kwargs)

            messages = self._build_messages(
                {"role": "user", "content": prompt}, **custom_kwargs
            )
            response = self.client.chat.completions.create(
                messages=messages, **openai_kwargs
            )
            return response.choices[0].message.content

        return self._retry_on_error(_execute)

    def get_stream(self, prompt: str, **kwargs) -> Iterable[str]:
        """Get a streaming response from the LLM"""

        def _execute():
            openai_kwargs, custom_kwargs = self._parse_openai_kwargs(**kwargs)
            messages = self._build_messages(
                {"role": "user", "content": prompt}, **custom_kwargs
            )
            response = self.client.chat.completions.create(
                messages=messages, stream=True, kwargs=openai_kwargs
            )
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content

        return self._retry_on_error(_execute)
