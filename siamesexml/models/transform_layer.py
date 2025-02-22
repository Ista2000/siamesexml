import os
import sys
import re
import torch.nn as nn
import models.residual_layer as residual_layer
import models.astec as astec
import json
from collections import OrderedDict


class _Identity(nn.Module):
    def __init__(self, *args, **kwargs):
        super(_Identity, self).__init__()

    def forward(self, x):
        # useful when x_ind is None
        x, x_ind = x
        return x

    def initialize(self, *args, **kwargs):
        pass


elements = {
    'dropout': nn.Dropout,
    'batchnorm1d': nn.BatchNorm1d,
    'linear': nn.Linear,
    'relu': nn.ReLU,
    'gelu': nn.GELU,
    'residual': residual_layer.Residual,
    '_residual': residual_layer.Residual,
    'identity': nn.Identity,
    '_identity': _Identity,
    'astec': astec.Astec
}


class Transform(nn.Module):
    """
    Transform document representation!
    transform_string: string for sequential pipeline
        eg relu#,dropout#p:0.1,residual#input_size:300-output_size:300
    params: dictionary like object for default params
        eg {emb_size:300}
    """

    def __init__(self, modules, device="cpu"):
        super(Transform, self).__init__()
        self.device = device
        if len(modules) == 1:
            self.transform = modules[0]
        else:
            self.transform = nn.Sequential(*modules)

    def forward(self, x):
        """
            Forward pass for transform layer
            Args:
                x: torch.Tensor: document representation
            Returns:
                x: torch.Tensor: transformed document representation
        """
        return self.encode(x)

    def encode(self, x):
        return self.transform(x)

    def _initialize(self, x):
        """Initialize parameters from existing ones
        Typically for word embeddings
        """
        if isinstance(self.transform, nn.Sequential):
            self.transform[0].initialize(x)
        else:
            self.transform.initialize(x)

    def initialize(self, x):
        # Currently implemented for:
        #  * initializing first module of nn.Sequential
        #  * initializing module
        self._initialize(x)

    def to(self):
        super().to(self.device)

    @property
    def representation_dims(self):
        # TODO: Hardcoded for now; compute it
        return 300

    def get_token_embeddings(self):
        return self.transform.get_token_embeddings()

    @property
    def sparse(self):
        try:
            _sparse = self.transform.sparse
        except AttributeError:
            _sparse = False
        return _sparse


def resolve_schema_args(jfile, ARGS):
    arguments = re.findall(r"#ARGS\.(.+?);", jfile)
    for arg in arguments:
        replace = '#ARGS.%s;' % (arg)
        to = str(ARGS.__dict__[arg])
        # Python True and False to json true & false
        if to == 'True' or to == 'False':
            to = to.lower()
        if jfile.find('\"#ARGS.%s;\"' % (arg)) != -1:
            replace = '\"#ARGS.%s;\"' % (arg)
            if isinstance(ARGS.__dict__[arg], str):
                to = str("\""+ARGS.__dict__[arg]+"\"")
        jfile = jfile.replace(replace, to)
    return jfile


def fetch_json(file, ARGS):
    with open(file, encoding='utf-8') as f:
        file = ''.join(f.readlines())
        schema = resolve_schema_args(file, ARGS)
    return json.loads(schema)


def get_functions(obj, params=None):
    return list(map(lambda x: elements[x](**obj[x]), obj['order']))
