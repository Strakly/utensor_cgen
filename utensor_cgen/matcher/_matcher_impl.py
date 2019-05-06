from collections import deque
from copy import deepcopy
from itertools import product
from random import choices
from string import ascii_letters, digits

import attr
from attr.validators import instance_of

from utensor_cgen.ir import (MetaOperationInfo, OperationInfo, uTensorGraph,
                             uTensorGraphView)
from utensor_cgen.matcher._morphism import Morphism
from utensor_cgen.utils import (ops_bfs_queue, prune_graph,
                                topologic_order_graph)

__all__ = ["uTensorGraphMatcher"]

@attr.s(frozen=True, slots=True)
class OpEqualityDelegate(object):

  # op_type -> list[tuple] (permutations)
  _association_map = {}
  # op_type -> dict[op_type] -> morphism
  _compatibility_map = {}

  @classmethod
  def is_associative(cls, permutations):
    def deco(op):
      if op.op_type in cls._association_map:
        raise ValueError(
          "duplicate associativity definition found for {}".format(op.op_type)
        )
      assert (
        isinstance(permutations, tuple) and 
        all([isinstance(perm, tuple) for perm in permutations])
      ), "`permutations` should be tuple of int tuples"
      cls._association_map[op.op_type] = permutations
      return op
    return deco

  @classmethod
  def is_compatible_with(cls, other_op_type, morphism_type, **kwargs):
    if not issubclass(morphism_type, Morphism):
      raise ValueError(
        'expecting Morphism for `morphism`, get {}'.format(morphism_type)
      )
    def deco(op):
      if op.op_type not in cls._compatibility_map:
        cls._compatibility_map[op.op_type] = {}
      if other_op_type in cls._compatibility_map[op.op_type]:
        raise RuntimeError(
          "Multiple morphisms from {} to {} detected".format(op.op_type, other_op_type)
        )
      if not other_op_type in cls._compatibility_map[op.op_type]:
        cls._compatibility_map[op.op_type][other_op_type] = morphism_type(**kwargs)
      return op
    return deco

  @classmethod
  def query(cls, sub_op, patrn_op):
    """
    Parameters
    ----------
    sub_op : OperationInfo
      the op in the subject ugraph
    patrn_op : OperationInfo
      the op in the pattern ugraph to match with

    Return
    ------
    is_eq : bool
      these two ops are equivalent if True, False o.w.
    equivalent_ops : List[OperationInfo]
      a list of equivalent ops derieved from `sub_op`
    """
    # to activate all configurations
    import utensor_cgen.backend.operators as _

    is_eq = False
    equivalent_ops = []
    if sub_op.op_type == patrn_op.op_type and sub_op.op_type not in cls._association_map:
      is_eq = True
      equivalent_ops = [patrn_op]
    elif sub_op.op_type == patrn_op.op_type:
      is_eq = True
      equivalent_ops = []
      for perm in cls._association_map[sub_op.op_type]:
        equivalent_ops.append(
          OperationInfo(
            name=sub_op.name,
            backend=sub_op.backend,
            ugraph=sub_op.ugraph,
            input_tensors=[sub_op.input_tensors[j] for j in perm],
            n_inputs=sub_op.n_inputs,
            output_tensors=sub_op.output_tensors,
            n_outputs=sub_op.n_outputs,
            op_type=sub_op.op_type,
            op_attr=sub_op.op_attr,
          )
        )
    elif patrn_op.op_type in cls._compatibility_map.get(sub_op.op_type, []):
      is_eq = True
      morphism = cls._compatibility_map[sub_op.op_type][patrn_op.op_type]
      equivalent_ops = [MetaOperationInfo(op_info=sub_op, morphism=morphism)]
    elif not patrn_op.input_tensors and \
      patrn_op.op_type == 'Placeholder':
      # match input node which is a placeholder anyway
      is_eq = True
      equivalent_ops = [sub_op]

    return is_eq, equivalent_ops

@attr.s
class uTensorGraphMatcher(object):

  pattern_ugraph = attr.ib(validator=instance_of(uTensorGraph))

  def _match(self, other_ugraph):
    outputs_pool = []
    for op in self.pattern_ugraph.output_ops:
      same_ops = other_ugraph.get_ops_by_type(op.op_type)
      if not same_ops:
        # there are missing output(s)
        # no way to match, return empty list
        return []
      outputs_pool.append(same_ops)
    output_candidates = product(*outputs_pool)
    for outputs in output_candidates:
      states = [
        _MatchState(
          match=uTensorGraphMatch(
            pattern_ugraph=self.pattern_ugraph,
            subject_ugraph=other_ugraph
          ),
          sub_bfs_queue=ops_bfs_queue(other_ugraph, init_nodes=outputs),
          patrn_bfs_queue=ops_bfs_queue(self.pattern_ugraph),
        )
      ]
      while True:
        visited_states = self._visit(states)
        if not visited_states:
          break
        states = []
        for state in visited_states:
          if state.is_done:
            yield state.match
          else:
            states.append(state)

  def match(self, other_ugraph, n=1):
    match_gen = self._match(other_ugraph)
    matches = []
    try:
      for _ in range(n):
        matches.append(next(match_gen))
    except StopIteration:
      pass
    return matches

  def match_all(self, other_ugraph):
    return list(self._match(other_ugraph))

  def _visit(self, states):
    # visit the state with a top-down bfs fashion
    # return the states that are still matched
    # import pdb; pdb.set_trace()
    new_states = []
    for state in states:
      match = state.match
      sub_op = state.sub_bfs_queue.popleft()
      patrn_op = state.patrn_bfs_queue.popleft()
      is_eq, eq_ops = OpEqualityDelegate.query(sub_op, patrn_op)
      if is_eq:
        for eq_op in eq_ops:
          new_sub_bfs_queue = deque(state.sub_bfs_queue)
          for _ in eq_op.input_nodes:
            new_sub_bfs_queue.popleft()
          for node in eq_op.input_nodes[::-1]:
            new_sub_bfs_queue.insert(0, node)
          new_state = _MatchState(
            match=uTensorGraphMatch(
              pattern_ugraph=match.pattern_ugraph,
              subject_ugraph=match.subject_ugraph,
              patrn2subj_op_map={k: v for k, v in match.patrn2subj_op_map.items()},
              subj2patrn_op_map={k: v for k, v in match.subj2patrn_op_map.items()},
              patrn2subj_tensor_map={k: v for k, v in match.patrn2subj_tensor_map.items()},
              subj2patrn_tensor_map={k: v for k, v in match.subj2patrn_tensor_map.items()}
            ),
            sub_bfs_queue=new_sub_bfs_queue,
            patrn_bfs_queue=deque(state.patrn_bfs_queue),
          )
          new_state.match.update_op_map(patrn_op, eq_op)
          new_states.append(new_state)
    return new_states

@attr.s
class uTensorGraphMatch(object):

  pattern_ugraph = attr.ib(type=uTensorGraph)
  subject_ugraph = attr.ib(type=uTensorGraph)

  # map from op_name to op_info
  patrn2subj_op_map = attr.ib(factory=dict)
  subj2patrn_op_map = attr.ib(factory=dict)
  # tensor in pattern -> tensor in target
  patrn2subj_tensor_map = attr.ib(factory=dict)
  # tensor in target -> tensor in pattern
  subj2patrn_tensor_map = attr.ib(factory=dict)

  def update_op_map(self, pattern_op, subj_op):
    self.patrn2subj_op_map[pattern_op.name] = subj_op
    self.subj2patrn_op_map[subj_op.name] = pattern_op
    for pattern_tensor, target_tensor in zip(pattern_op.input_tensors, subj_op.input_tensors):
      self.patrn2subj_tensor_map[pattern_tensor.name] = target_tensor
      self.subj2patrn_tensor_map[target_tensor.name] = pattern_tensor
  
  @property
  def is_valid(self):
    """Check if the match is valid
    1. only input/output ops of the subgraph view are allowed to have external linkage
    2. input ops have only external linkage for its inputs
    3. output ops have only external linkage for its outputs

    If any of above fail, there is no trivial way to determine how to replace the matched
    subgraph other than very hard code way.
    """
    subj_view = self.subject_graph_view
    valid = True
    checked_ops = set()
    for in_op in subj_view.input_ops:
      for op in in_op.output_nodes:
        if op.name not in subj_view.ops_info:
          valid = False
      checked_ops.add(in_op.name)
    for out_op in subj_view.output_ops:
      for op in out_op.input_nodes:
        if op.name not in subj_view.ops_info:
          valid = False
      checked_ops.add(out_op.name)
    
    for name, op in subj_view.ops_info.items():
      if name in checked_ops:
        continue
      for in_op in op.input_nodes:
        if in_op.name not in subj_view.ops_info:
          valid = False
      for out_op in op.output_nodes:
        if out_op.name not in subj_view.ops_info:
          valid = Falses
    return valid
    
  def replace_with(self, callback, suffix=None):
    """
    Replace matched subgraph with a given ugraph given by the callback, *not in place*

    Arguments
    ---------
    callback : callable

    Return
    ------
    new_ugraph : uTensorGraph
      a *new* graph with matched subgraph replaced with the graph given by the callback
    """
    # build a matched subgraph and pass it to callback
    # input_map (dict): 
    #  {
    #     (input op name of pattern graph, index) : (op name of replacing graph, index)
    #  }
    # output_map (dict):
    #  {
    #     (output op name of pattern graph, index) : (op name of replacing graph, index)
    #  }
    replace_ugraph, input_map, output_map = callback(self)
    replaceible, reasons = self._is_replacible(replace_ugraph, input_map, output_map)
    if not replaceible:
      raise ValueError(
        'matched subgraph can not be replaced with the ugraph given: {}'.format(reasons)
      )
    replace_ugraph, input_map, output_map = self.new_ugraph_with_suffix(
      replace_ugraph, input_map, output_map, suffix
    )
    new_ugraph = deepcopy(self.subject_ugraph)
    subj_graph_view = self.subject_graph_view
    # replacing input tensors
    for (patrn_op_name, patrn_idx), (repl_op_name, repl_idx) in input_map.items():
      subj_op = self.patrn2subj_op_map[patrn_op_name]
      subj_in_tensor = subj_op.input_tensors[patrn_idx]
      repl_op = replace_ugraph.ops_info[repl_op_name]
      repl_op.input_tensors[repl_idx] = subj_in_tensor
    # replacing output tensors

    new_ugraph = prune_graph(new_ugraph)
    return new_ugraph

  def _is_replacible(self, replace_ugraph, input_map, output_map):
    """Given a ugraph to replace with, check if it's replacible with 
    the matched sub ugraph
    """
    replacible = True
    reasons = []
    if not self.is_valid:
      replaceible = False
      reasons.append('the match is not valid')
    subj_graph_view = self.subject_graph_view
    if len(input_map) != len(subj_graph_view.input_tensors):
      replacible = False
      reasons.append('the number of input tensors does not match')
    if len(output_map) != len(subj_graph_view.output_tensors):
      replacible = False
      reasons.append('the number of output tensors does not match')
    for in_patrn_op_name, _ in input_map:
      if not in_patrn_op_name in self.pattern_ugraph.ops_info:
        replacible = False
        reasons.append(
          '{} is not found in the pattern graph'.format(in_patrn_op_name)
        )
        continue
    for out_patrn_op_name, _ in output_map:
      if not out_patrn_op_name in self.pattern_ugraph.ops_info:
        replacible = False
        reasons.append(
          '{} is not found in the pattern graph'.format(out_patrn_op_name)
        )
    return replacible, reasons

  CHARSET = ascii_letters + digits

  @classmethod
  def _random_suffix(cls, length=8):
    chars = choices(cls.CHARSET, k=length)
    return ''.join(chars)

  @classmethod
  def new_ugraph_with_suffix(cls, ugraph, input_map, output_map, suffix=None):
    if suffix is None:
      suffix = cls._random_suffix()
    new_input_map = {}
    for (op_name, idx), v in input_map.items():
      new_input_map[('{}_{}'.format(op_name, suffix), idx)] = v
    new_output_map = {}
    for (op_name, idx), v in output_map.items():
      new_output_map[('{}_{}'.format(op_name, suffix), idx)] = v
    new_ugraph = deepcopy(ugraph)
    new_ugraph.output_nodes = [
      '{}_{}'.format(name, suffix) for name in ugraph.output_nodes
    ]
    new_ugraph.topo_order = ['{}_{}'.format(name, suffix) for name in ugraph.topo_order]
    ops_to_remove = set([])
    new_ops_info = {}
    for ori_op_name, op in new_ugraph.ops_info.items():
      new_op_name = '{}_{}'.format(ori_op_name, suffix)
      op.name = new_op_name
      for tensor in op.output_tensors:
        tensor_idx = tensor.name.split(':')[1]
        tensor.name = '{}_{}:{}'.format(tensor.op_name, suffix, tensor_idx)
        tensor.op_name = new_op_name
      for tensor in op.input_tensors:
        in_op_name, tensor_idx = tensor.name.split(':')
        new_in_op_name = '{}_{}'.format(in_op_name, suffix)
        tensor.name = '{}:{}'.format(new_in_op_name, tensor_idx)
        tensor.op_name = new_in_op_name
      ops_to_remove.add(ori_op_name)
      new_ops_info[new_op_name] = op
    for op_name in ops_to_remove:
      new_ugraph.ops_info.pop(op_name)
    new_ugraph.ops_info = new_ops_info
    return new_ugraph, new_input_map, new_output_map

  @property
  def subject_graph_view(self):
    output_nodes = [
      self.patrn2subj_op_map[name].name
      for name in self.pattern_ugraph.output_nodes
    ]
    op_names = list(self.subj2patrn_op_map.keys())
    return uTensorGraphView(
      ugraph=self.subject_ugraph,
      op_names=op_names,
      output_nodes=output_nodes,
    )


@attr.s
class _MatchState(object):
  match = attr.ib()
  @match.validator
  def check(self, attrib, value):
    if not isinstance(value, uTensorGraphMatch):
      raise ValueError(
        'expecting a uTensorGraphMatch, get {}'.format(type(value))
      )
  # sub_bfs_queue is a queue for BFS of the subject ugraph
  sub_bfs_queue = attr.ib(validator=instance_of(deque))
  # consume_queue is a queue defines the matching order of pattern ugraph
  patrn_bfs_queue = attr.ib(validator=instance_of(deque))
  visited = attr.ib(init=False, factory=set)

  @property
  def is_done(self):
    """
    a state is done, if
    1. the patrn_bfs_queue is empty
    """
    return not self.patrn_bfs_queue