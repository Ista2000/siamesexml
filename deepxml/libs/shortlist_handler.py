import numpy as np
import _pickle as pickle
import operator
import os
from .lookup import Table
from .negative_sampling import NegativeSampler
from scipy.sparse import load_npz
from xclib.utils import sparse as sp
from .utils import add_noise


def construct_handler(shortlist_method, num_labels, shortlist=None,
                      model_dir='', mode='train', size_shortlist=-1,
                      label_mapping=None, in_memory=True,
                      shorty=None, corruption=200):
    if shortlist_method == 'static':
        return ShortlistHandlerStatic(
            num_labels, model_dir, mode, size_shortlist,
            in_memory, label_mapping)
    elif shortlist_method == 'extended':
        return ShortlistHandlerExtended(
            num_labels, model_dir, mode, size_shortlist,
            in_memory, label_mapping, corruption)
    elif shortlist_method == 'hybrid':
        return ShortlistHandlerHybrid(
            num_labels, model_dir, mode, size_shortlist,
            in_memory, label_mapping, corruption)
    elif shortlist_method == 'dynamic':
        return ShortlistHandlerDynamic(
            num_labels, shorty, model_dir, mode, size_shortlist,
            label_mapping)
    else:
        raise NotImplementedError(
            "Unknown shortlist method: {}!".format(shortlist_method))


class ShortlistHandlerBase(object):
    """Base class for ShortlistHandler
    - support for multiple representations for labels

    Parameters
    ----------
    num_labels: int
        number of labels
    shortlist:
        shortlist object
    model_dir: str, optional, default=''
        save the data in model_dir
    mode: str: optional, default=''
        mode i.e. train or test or val
    size_shortlist:int, optional, default=-1
        get shortlist of this size
    label_mapping: None or dict: optional, default=None
        map labels as per this mapping
    """

    def __init__(self, num_labels, shortlist, model_dir='',
                 mode='train', size_shortlist=-1, label_mapping=None):
        self.model_dir = model_dir
        self.size_shortlist = size_shortlist
        self.mode = mode
        self.num_labels = num_labels
        self.label_mapping = label_mapping
        # self._create_shortlist(shortlist)
        self.label_padding_index = self.num_labels

    def _create_shortlist(self, shortlist):
        """
            Create structure to hold shortlist
        """
        self.shortlist = shortlist

    def query(self, *args, **kwargs):
        return self.shortlist(*args, **kwargs)

    def _pad_seq(self, indices, sim):
        _pad_length = self.size_shortlist - len(indices)
        indices.extend([self.label_padding_index]*_pad_length)
        sim.extend([-100]*_pad_length)

    def _adjust_shortlist(self, pos_labels, shortlist, sim, min_nneg=100):
        """
            Adjust shortlist for a instance
            Training: Add positive labels to the shortlist
            Inference: Return shortlist with label mask
        """
        if self.mode == 'train':
            labels_mask = np.zeros(self.size_shortlist, dtype=np.float32)
            sim_mask = np.zeros(self.size_shortlist, dtype=np.float32)
            label_shortlist = np.full(
                self.size_shortlist, fill_value=self.label_padding_index,
                dtype=np.int64)
            # TODO: Adjust dist as well
            # If number of positives are more than shortlist_size
            if len(pos_labels) > self.size_shortlist:
                _ind = np.random.choice(
                    len(pos_labels), size=self.size_shortlist-min_nneg,
                    replace=False)
                pos_labels = np.fromiter(
                    operator.itemgetter(*_ind)(pos_labels),
                    dtype=np.int64)
            neg_labels = np.fromiter(
                filter(lambda x: x not in set(pos_labels), shortlist),
                dtype=np.int64)
            labels_mask[:len(pos_labels)] = 1.0
            sim_mask[:len(pos_labels)] = 1.0 # not used during training; not perfect values
            _shortlist = np.concatenate([pos_labels, neg_labels])
            label_shortlist[:min(len(_shortlist), self.size_shortlist)] = _shortlist[:min(len(_shortlist), self.size_shortlist)]
        else:
            labels_mask = np.zeros(self.size_shortlist, dtype=np.float32)
            label_shortlist = np.full(
                self.size_shortlist, fill_value=self.label_padding_index,
                dtype=np.int64)
            label_shortlist[:len(shortlist)] = shortlist
            pos_labels = set(pos_labels)
            for idx, item in enumerate(shortlist):
                if item in pos_labels:                
                    labels_mask[idx] = 1
            sim_mask = np.zeros(self.size_shortlist, dtype=np.float32)
            sim_mask[:len(shortlist)] = sim
        return label_shortlist, labels_mask, sim_mask

    def _get_sl(self, index, pos_labels):
        if self.shortlist.data_init:
            shortlist, sim = self.query(index)
            shortlist, labels_mask, sim = self._adjust_shortlist(
                pos_labels, shortlist, sim)
        else:
            shortlist = np.zeros(self.size_shortlist, dtype=np.int64) 
            labels_mask = np.zeros(self.size_shortlist, dtype=np.float32)
            sim = np.zeros(self.size_shortlist, dtype=np.float32)
        return shortlist, labels_mask, sim

    def get_shortlist(self, index, pos_labels=None):
        """
            Get data with shortlist for given data index
        """
        return self._get_sl(index, pos_labels)


class ShortlistHandlerStatic(ShortlistHandlerBase):
    """ShortlistHandler with static shortlist
    - save/load/update/process shortlist
    Parameters
    ----------
    num_labels: int
        number of labels
    model_dir: str, optional, default=''
        save the data in model_dir
    mode: str: optional, default=''
        mode i.e. train or test or val
    size_shortlist:int, optional, default=-1
        get shortlist of this size
    in_memory: bool: optional, default=True
        Keep the shortlist in memory or on-disk
    label_mapping: None or dict: optional, default=None
        map labels as per this mapping
    """

    def __init__(self, num_labels, model_dir='', mode='train',
                 size_shortlist=-1, in_memory=True, label_mapping=None):
        super().__init__(num_labels, None, model_dir, mode,
                         size_shortlist, label_mapping)
        self.in_memory = in_memory
        self._create_shortlist()

    def query(self, index):
        shortlist = self.shortlist.query(index)
        sim = self.sim.query(index)
        return shortlist, sim

    def _create_shortlist(self):
        """
            Create structure to hold shortlist
        """
        _type = 'memory' if self.in_memory else 'memmap'
        self.shortlist = Table(_type=_type, _dtype=np.int64)
        self.sim = Table(_type=_type, _dtype=np.float32)

    def update_shortlist(self, shortlist, sim, fname='tmp', idx=-1):
        """
            Update label shortlist for each instance
        """
        prefix = 'train' if self.mode == 'train' else 'test'
        self.shortlist.create(shortlist, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.indices'.format(fname, prefix)),
            idx)
        self.sim.create(sim, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.sim'.format(fname, prefix)),
            idx)
        del sim, shortlist

    def save_shortlist(self, fname):
        """
            Save label shortlist and similarity for each instance
        """
        self.shortlist.save(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.save(os.path.join(self.model_dir, fname+'.shortlist.sim'))

    def load_shortlist(self, fname):
        """
            Load label shortlist and similarity for each instance
        """
        self.shortlist.load(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.load(os.path.join(self.model_dir, fname+'.shortlist.sim'))


class ShortlistHandlerDynamic(ShortlistHandlerBase):
    """ShortlistHandler with dynamic shortlist
    - support for multiple representations for labels

    Parameters
    ----------
    num_labels: int
        number of labels
    shortlist:
        shortlist object like negative sampler
    model_dir: str, optional, default=''
        save the data in model_dir
    mode: str: optional, default=''
        mode i.e. train or test or val
    size_shortlist:int, optional, default=-1
        get shortlist of this size
    label_mapping: None or dict: optional, default=None
        map labels as per this mapping
    """

    def __init__(self, num_labels, shortlist, model_dir='',
                 mode='train', size_shortlist=-1, label_mapping=None):
        super().__init__(num_labels, shortlist, model_dir, mode,
                         size_shortlist, label_mapping)
        self._create_shortlist(shortlist)

    def query(self, index):
        return self.shortlist.query(num_samples=1)


class ShortlistHandlerHybrid(ShortlistHandlerBase):
    """ShortlistHandler with hybrid shortlist
    - save/load/update/process shortlist
    - support for multiple representations for labels
    Parameters
    ----------
    num_labels: int
        number of labels
    model_dir: str, optional, default=''
        save the data in model_dir
    mode: str: optional, default=''
        mode i.e. train or test or val
    size_shortlist:int, optional, default=-1
        get shortlist of this size
    in_memory: bool: optional, default=True
        Keep the shortlist in memory or on-disk
    label_mapping: None or dict: optional, default=None
        map labels as per this mapping
    _corruption: int, optional, default=None
        add these many random labels
    """

    def __init__(self, num_labels, model_dir='', mode='train',
                 size_shortlist=-1, in_memory=True,
                 label_mapping=None, _corruption=200):
        super().__init__(num_labels, None, model_dir, mode,
                         size_shortlist, label_mapping)
        self.in_memory = in_memory
        self._create_shortlist()
        # Some labels will be repeated, so keep it low
        self.shortlist_dynamic = NegativeSampler(
            num_labels, _corruption+350, replace=True)
        self.size_shortlist = size_shortlist+_corruption  # Both

    def query(self, index):
        shortlist = self.shortlist.query(index)
        sim = self.sim.query(index)
        _shortlist, _sim = self.shortlist_dynamic.query(1)
        shortlist = np.concatenate([shortlist, _shortlist])
        sim = np.concatenate([sim, _sim])
        return shortlist, sim

    def _create_shortlist(self):
        """
            Create structure to hold shortlist
        """
        _type = 'memory' if self.in_memory else 'memmap'
        self.shortlist = Table(_type=_type, _dtype=np.int64)
        self.sim = Table(_type=_type, _dtype=np.float32)

    def update_shortlist(self, shortlist, sim, fname='tmp', idx=-1):
        """
            Update label shortlist for each instance
        """
        prefix = 'train' if self.mode == 'train' else 'test'
        self.shortlist.create(shortlist, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.indices'.format(fname, prefix)),
            idx)
        self.sim.create(sim, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.sim'.format(fname, prefix)),
            idx)
        del sim, shortlist

    def save_shortlist(self, fname):
        """
            Save label shortlist and similarity for each instance
        """
        self.shortlist.save(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.save(os.path.join(self.model_dir, fname+'.shortlist.sim'))

    def load_shortlist(self, fname):
        """
            Load label shortlist and similarity for each instance
        """
        self.shortlist.load(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.load(os.path.join(
            self.model_dir, fname+'.shortlist.sim'))


class ShortlistHandlerExtended(ShortlistHandlerBase):
    """ShortlistHandler with hybrid shortlist
    - save/load/update/process shortlist
    - support for multiple representations for labels
    Parameters
    ----------
    num_labels: int
        number of labels
    model_dir: str, optional, default=''
        save the data in model_dir
    mode: str: optional, default=''
        mode i.e. train or test or val
    size_shortlist:int, optional, default=-1
        get shortlist of this size
    in_memory: bool: optional, default=True
        Keep the shortlist in memory or on-disk
    label_mapping: None or dict: optional, default=None
        map labels as per this mapping
    _corruption: int, optional, default=None
        add these many random labels
    """

    def __init__(self, num_labels, model_dir='', mode='train',
                 size_shortlist=-1, in_memory=True,
                 label_mapping=None, _corruption=200):
        super().__init__(num_labels, None, model_dir, mode,
                         size_shortlist, label_mapping)
        self.in_memory = in_memory
        self._create_shortlist()
        # Some labels will be repeated, so keep it low
        self.shortlist_dynamic = None
        self.size_shortlist = size_shortlist+_corruption  # Both

    def update_dynamic(self, shortlist):
        self.shortlist_dynamic = shortlist

    def query(self, index):
        shortlist = self.shortlist.query(index)
        sim = self.sim.query(index)
        _shortlist = self.shortlist_dynamic[index]
        shortlist = np.concatenate([shortlist, _shortlist])
        sim = np.concatenate([sim, np.zeros(len(_shortlist), dtype=np.float32)])
        return shortlist, sim

    def _create_shortlist(self):
        """
            Create structure to hold shortlist
        """
        _type = 'memory' if self.in_memory else 'memmap'
        self.shortlist = Table(_type=_type, _dtype=np.int64)
        self.sim = Table(_type=_type, _dtype=np.float32)

    def update_shortlist(self, shortlist, sim, fname='tmp', idx=-1):
        """
            Update label shortlist for each instance
        """
        prefix = 'train' if self.mode == 'train' else 'test'
        self.shortlist.create(shortlist, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.indices'.format(fname, prefix)),
            idx)
        self.sim.create(sim, os.path.join(
            self.model_dir,
            '{}.{}.shortlist.sim'.format(fname, prefix)),
            idx)
        del sim, shortlist

    def save_shortlist(self, fname):
        """
            Save label shortlist and similarity for each instance
        """
        self.shortlist.save(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.save(os.path.join(self.model_dir, fname+'.shortlist.sim'))

    def load_shortlist(self, fname):
        """
            Load label shortlist and similarity for each instance
        """
        self.shortlist.load(os.path.join(
            self.model_dir, fname+'.shortlist.indices'))
        self.sim.load(os.path.join(
            self.model_dir, fname+'.shortlist.sim'))
