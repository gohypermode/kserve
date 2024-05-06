# Copyright 2024 The KServe Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest

import torch.nn.functional as F
import torch
from kserve.model import PredictorConfig
from kserve.protocol.rest.openai import ChatCompletionRequest, CompletionRequest
from kserve.protocol.rest.openai.types import (
    CreateChatCompletionRequest,
    CreateCompletionRequest,
)
from pytest_httpx import HTTPXMock
from transformers import AutoConfig

from .task import infer_task_from_model_architecture
from .encoder_model import HuggingfaceEncoderModel
from .generative_model import HuggingfaceGenerativeModel
from .task import MLTask


@pytest.fixture(scope="module")
def bloom_model():
    model = HuggingfaceGenerativeModel(
        "bloom-560m",
        model_id_or_path="bigscience/bloom-560m",
    )
    model.load()
    yield model
    model.stop()


@pytest.fixture(scope="module")
def t5_model():
    model = HuggingfaceGenerativeModel(
        "t5-small",
        model_id_or_path="google-t5/t5-small",
        max_length=512,
    )
    model.load()
    yield model
    model.stop()


@pytest.fixture(scope="module")
def bert_base_model():
    model = HuggingfaceEncoderModel(
        "google-bert/bert-base-uncased",
        model_id_or_path="bert-base-uncased",
        do_lower_case=True,
    )
    model.load()
    yield model
    model.stop()


@pytest.fixture(scope="module")
def bert_base_yelp_polarity():
    model = HuggingfaceEncoderModel(
        "bert-base-uncased-yelp-polarity",
        model_id_or_path="textattack/bert-base-uncased-yelp-polarity",
        task=MLTask.sequence_classification,
    )
    model.load()
    yield model
    model.stop()

@pytest.fixture(scope="module")
def distilbert_base_uncased_finetuned_sst_2_english():
    model = HuggingfaceEncoderModel(
        "distilbert-base-uncased-finetuned-sst-2-english",
        model_id_or_path="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        do_lower_case=True,
    )
    model.load()
    yield model
    model.stop()

@pytest.fixture(scope="module")
def bert_token_classification():
    model = HuggingfaceEncoderModel(
        "bert-large-cased-finetuned-conll03-english",
        model_id_or_path="dbmdz/bert-large-cased-finetuned-conll03-english",
        do_lower_case=True,
        add_special_tokens=False,
    )
    model.load()
    yield model
    model.stop()

@pytest.fixture(scope="module")
def text_embedding():
    model = HuggingfaceEncoderModel(
        "mxbai-embed-large-v1",
        model_id_or_path="mixedbread-ai/mxbai-embed-large-v1",
        task=MLTask.text_embedding,
    )
    model.load()
    yield model
    model.stop()


def test_unsupported_model():
    config = AutoConfig.from_pretrained("google/tapas-base-finetuned-wtq")
    with pytest.raises(ValueError) as err_info:
        infer_task_from_model_architecture(config)
    assert "Task table_question_answering is not supported" in err_info.value.args[0]


@pytest.mark.asyncio
async def test_t5(t5_model: HuggingfaceGenerativeModel):
    params = CreateCompletionRequest(
        model="t5-small",
        prompt="translate from English to German: we are making words",
        stream=False,
    )
    request = CompletionRequest(params=params)
    response = await t5_model.create_completion(request)
    assert response.choices[0].text == "wir setzen Worte"


@pytest.mark.asyncio
async def test_t5_bad_params(t5_model: HuggingfaceGenerativeModel):
    params = CreateCompletionRequest(
        model="t5-small",
        prompt="translate from English to German: we are making words",
        echo=True,
        stream=False,
    )
    request = CompletionRequest(params=params)
    with pytest.raises(ValueError) as err_info:
        await t5_model.create_completion(request)
    assert err_info.value.args[0] == "'echo' is not supported by encoder-decoder models"


@pytest.mark.asyncio
async def test_bert(bert_base_model: HuggingfaceEncoderModel):
    response = await bert_base_model(
        {
            "instances": [
                "The capital of France is [MASK].",
                "The capital of [MASK] is paris.",
            ]
        },
        headers={},
    )
    assert response == {"predictions": ["paris", "france"]}


@pytest.mark.asyncio
async def test_model_revision(request: HuggingfaceEncoderModel):
    # https://huggingface.co/google-bert/bert-base-uncased
    commit = "86b5e0934494bd15c9632b12f734a8a67f723594"
    model = HuggingfaceEncoderModel(
        "google-bert/bert-base-uncased",
        model_id_or_path="bert-base-uncased",
        model_revision=commit,
        tokenizer_revision=commit,
        do_lower_case=True,
    )
    model.load()
    request.addfinalizer(model.stop)

    response = await model(
        {
            "instances": [
                "The capital of France is [MASK].",
                "The capital of [MASK] is paris.",
            ]
        },
        headers={},
    )
    assert response == {"predictions": ["paris", "france"]}


@pytest.mark.asyncio
async def test_bert_predictor_host(request, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json={
            "outputs": [
                {
                    "name": "OUTPUT__0",
                    "shape": [1, 9, 758],
                    "data": [1] * 9 * 758,
                    "datatype": "INT64",
                }
            ]
        }
    )

    model = HuggingfaceEncoderModel(
        "bert",
        model_id_or_path="google-bert/bert-base-uncased",
        tensor_input_names="input_ids",
        predictor_config=PredictorConfig(
            predictor_host="localhost:8081", predictor_protocol="v2"
        ),
    )
    model.load()
    request.addfinalizer(model.stop)

    response = await model(
        {"instances": ["The capital of France is [MASK]."]}, headers={}
    )
    assert response == {"predictions": ["[PAD]"]}


@pytest.mark.asyncio
async def test_bert_sequence_classification(bert_base_yelp_polarity):
    request = "Hello, my dog is cute."
    response = await bert_base_yelp_polarity(
        {"instances": [request, request]}, headers={}
    )
    assert response == {"predictions": [
            {
                'confidence': 0.9988189339637756,
                'label': "LABEL_1",
                'probabilities': [
                    {'label': "LABEL_0", 'probability': 0.0011810670839622617},
                    {'label': "LABEL_1", 'probability': 0.9988189339637756}
                ]
            },
            {
                'confidence': 0.9988189339637756,
                'label': "LABEL_1",
                'probabilities': [
                    {'label': "LABEL_0", 'probability': 0.0011810670839622617},
                    {'label': "LABEL_1", 'probability': 0.9988189339637756}
                ]
            }
        ]
    }

@pytest.mark.asyncio
async def test_infer_labels_from_config(distilbert_base_uncased_finetuned_sst_2_english):
    request = "Hello, my dog is cute."
    response = await distilbert_base_uncased_finetuned_sst_2_english(
        {"instances": [request, request]}, headers={}
    )
    # verify that the label(s) are inferred from the model config:
    # https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english/blob/main/config.json
    assert response["predictions"][0]["label"] == "POSITIVE"


@pytest.mark.asyncio
async def test_bert_token_classification(bert_token_classification):
    request = "HuggingFace is a company based in Paris and New York"
    response = await bert_token_classification(
        {"instances": [request, request]}, headers={}
    )
    assert response == {
        'predictions': [
            [
                {'entity': 'I-ORG', 'score': 0.9972999691963196, 'index': 1, 'word': 'Hu', 'start': 0, 'end': 2},
                {'entity': 'I-ORG', 'score': 0.9716504216194153, 'index': 2, 'word': '##gging', 'start': 2, 'end': 7},
                {'entity': 'I-ORG', 'score': 0.9962745904922485, 'index': 3, 'word': '##F', 'start': 7, 'end': 8},
                {'entity': 'I-ORG', 'score': 0.993005096912384, 'index': 4, 'word': '##ace', 'start': 8, 'end': 11},
                {'entity': 'I-LOC', 'score': 0.9940695762634277, 'index': 10, 'word': 'Paris', 'start': 34, 'end': 39},
                {'entity': 'I-LOC', 'score': 0.9982321858406067, 'index': 12, 'word': 'New', 'start': 44, 'end': 47},
                {'entity': 'I-LOC', 'score': 0.9975290894508362, 'index': 13, 'word': 'York', 'start': 48, 'end': 52}
            ], 
            [
                {'entity': 'I-ORG', 'score': 0.9972999691963196, 'index': 1, 'word': 'Hu', 'start': 0, 'end': 2},
                {'entity': 'I-ORG', 'score': 0.9716504216194153, 'index': 2, 'word': '##gging', 'start': 2, 'end': 7},
                {'entity': 'I-ORG', 'score': 0.9962745904922485, 'index': 3, 'word': '##F', 'start': 7, 'end': 8},
                {'entity': 'I-ORG', 'score': 0.993005096912384, 'index': 4, 'word': '##ace', 'start': 8, 'end': 11},
                {'entity': 'I-LOC', 'score': 0.9940695762634277, 'index': 10, 'word': 'Paris', 'start': 34, 'end': 39},
                {'entity': 'I-LOC', 'score': 0.9982321858406067, 'index': 12, 'word': 'New', 'start': 44, 'end': 47},
                {'entity': 'I-LOC', 'score': 0.9975290894508362, 'index': 13, 'word': 'York', 'start': 48, 'end': 52}]
        ]
    }

@pytest.mark.asyncio
async def test_text_embedding(text_embedding):
    def cosine_similarity(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        if len(a.shape) == 1:
            a = a.unsqueeze(0)

        if len(b.shape) == 1:
            b = b.unsqueeze(0)

        a_norm = F.normalize(a, p=2, dim=1)
        b_norm = F.normalize(b, p=2, dim=1)
        return torch.mm(a_norm, b_norm.transpose(0, 1))

    requests = ["I'm happy", "I'm full of happiness", "They were born in the capital city of France, Paris"]
    response = await text_embedding({"instances": requests}, headers={})
    predictions = response["predictions"]

    print(cosine_similarity(torch.tensor(predictions[0]), torch.tensor(predictions[1]))[0])
    print(cosine_similarity(torch.tensor(predictions[0]), torch.tensor(predictions[2]))[0])
    assert cosine_similarity(torch.tensor(predictions[0]), torch.tensor(predictions[1]))[0] > 0.9
    assert cosine_similarity(torch.tensor(predictions[0]), torch.tensor(predictions[2]))[0] < 0.6

@pytest.mark.asyncio
async def test_bloom_completion(bloom_model: HuggingfaceGenerativeModel):
    params = CreateCompletionRequest(
        model="bloom-560m",
        prompt="Hello, my dog is cute",
        stream=False,
        echo=True,
    )
    request = CompletionRequest(params=params)
    response = await bloom_model.create_completion(request)
    assert (
        response.choices[0].text
        == "Hello, my dog is cute.\n- Hey, my dog is cute.\n- Hey, my dog is cute"
    )


@pytest.mark.asyncio
async def test_bloom_completion_streaming(bloom_model: HuggingfaceGenerativeModel):
    params = CreateCompletionRequest(
        model="bloom-560m",
        prompt="Hello, my dog is cute",
        stream=True,
        echo=False,
    )
    request = CompletionRequest(params=params)
    response = await bloom_model.create_completion(request)
    output = ""
    async for chunk in response:
        output += chunk.choices[0].text
    assert output == ".\n- Hey, my dog is cute.\n- Hey, my dog is cute"


@pytest.mark.asyncio
async def test_bloom_chat_completion(bloom_model: HuggingfaceGenerativeModel):
    messages = [
        {
            "role": "system",
            "content": "You are a friendly chatbot who always responds in the style of a pirate",
        },
        {
            "role": "user",
            "content": "How many helicopters can a human eat in one sitting?",
        },
    ]
    params = CreateChatCompletionRequest(
        model="bloom-560m",
        messages=messages,
        stream=False,
    )
    request = ChatCompletionRequest(params=params)
    response = await bloom_model.create_chat_completion(request)
    assert (
        response.choices[0].message.content
        == "The first thing you need to do is to get a good idea of what you are looking for"
    )


@pytest.mark.asyncio
async def test_bloom_chat_completion_streaming(bloom_model: HuggingfaceGenerativeModel):
    messages = [
        {
            "role": "system",
            "content": "You are a friendly chatbot who always responds in the style of a pirate",
        },
        {
            "role": "user",
            "content": "How many helicopters can a human eat in one sitting?",
        },
    ]
    params = CreateChatCompletionRequest(
        model="bloom-560m",
        messages=messages,
        stream=True,
    )
    request = ChatCompletionRequest(params=params)
    response = await bloom_model.create_chat_completion(request)
    output = ""
    async for chunk in response:
        output += chunk.choices[0].delta.content
    assert (
        output
        == "The first thing you need to do is to get a good idea of what you are looking for"
    )


@pytest.mark.asyncio
async def test_input_padding(bert_base_yelp_polarity: HuggingfaceEncoderModel):
    # inputs with different lengths will throw an error
    # unless we set padding=True in the tokenizer
    request_one = "Hello, my dog is cute."
    request_two = "Hello there, my dog is cute."
    response = await bert_base_yelp_polarity(
        {"instances": [request_one, request_two]}, headers={}
    )
    assert response == {
        "predictions": [
            {
                'confidence': 0.9988189339637756,
                'label': "LABEL_1",
                'probabilities': [
                    {'label': "LABEL_0", 'probability': 0.0011810670839622617},
                    {'label': "LABEL_1", 'probability': 0.9988189339637756}
                ]
            },
            {
                'confidence': 0.9963782429695129,
                'label': "LABEL_1",
                'probabilities': [
                    {'label': "LABEL_0", 'probability': 0.003621795680373907},
                    {'label': "LABEL_1", 'probability': 0.9963782429695129}
                ]
            }
        ]
    }


@pytest.mark.asyncio
async def test_input_truncation(bert_base_yelp_polarity: HuggingfaceEncoderModel):
    # bert-base-uncased has a max length of 512 (tokenizer.model_max_length).
    # this request exceeds that, so it will throw an error
    # unless we set truncation=True in the tokenizer
    request = "good " * 600
    response = await bert_base_yelp_polarity({"instances": [request]}, headers={})
    assert response == {
        "predictions": [
            {
                'confidence': 0.9914830327033997, 
                'label': "LABEL_1", 
                'probabilities': [
                    {'label': "LABEL_0", 'probability': 0.00851691048592329}, 
                    {'label': "LABEL_1", 'probability': 0.9914830327033997}
                ]
            }
        ]
    }
