from utensor_cgen.matcher import uTensorGraphMatcher


def test_id_match(patrn_ugraph):
    matcher = uTensorGraphMatcher(patrn_ugraph)
    matches = matcher.match(patrn_ugraph)
    assert matches, 'expecting matches, get {} matches'.format(len(matches))
    match = matches[0]
    for name, op in match.patrn2subj_op_map.items():
        assert name == op.name, '{} <--> {}'.format(name, op.name)
    for name, op in match.subj2patrn_op_map.items():
        assert name == op.name, '{} <--> {}'.format(name, op.name)
    for tensor in patrn_ugraph.input_tensors:
        assert tensor.name in match.patrn2subj_tensor_map, \
            '{} is missing'.format(tensor.name)
    for tensor in patrn_ugraph.output_tensors:
        assert tensor.name in match.subj2patrn_tensor_map, \
            '{} is missing'.format(tensor.name)

def test_match_sub1(patrn_ugraph, subject_ugraph1):
    matcher = uTensorGraphMatcher(patrn_ugraph)
    matches = matcher.match_all(subject_ugraph1)
    assert matches, 'expecting matches, get {} matches'.format(len(matches))
    match = matches[0]
    assert len(matches) == 2, 'should be exactly two match, get {}'.format(len(matches))
    assert match.patrn2subj_op_map['input0'].name == 'sub_input0'
    assert match.patrn2subj_op_map['input1'].name == 'sub_input1'
    assert match.patrn2subj_op_map['add0'].name == 'sub_add0'
    assert match.patrn2subj_op_map['output'].name == 'sub_add1'

def test_match_sub1_1(patrn_ugraph, subject_ugraph1_1):
    matcher = uTensorGraphMatcher(patrn_ugraph)
    matches = matcher.match(subject_ugraph1_1)
    assert matches, 'expecting matches, get {} matches'.format(len(matches))
    match = matches[0]
    assert match.patrn2subj_op_map['input0'].name in ['sub_input0', 'sub_input1']
    assert match.patrn2subj_op_map['input1'].name in ['sub_input0', 'sub_input1']
    assert match.patrn2subj_op_map['add0'].name == 'sub_add0'
    assert match.patrn2subj_op_map['output'].name == 'sub_add1'

def test_match_sub1_2(patrn_ugraph, subject_ugraph1_2):
    matcher = uTensorGraphMatcher(patrn_ugraph)
    matches = matcher.match(subject_ugraph1_2)
    assert matches, 'expecting matches, get {} matches'.format(len(matches))
    match = matches[0]
    assert match.patrn2subj_op_map['input0'].name in ['sub_input0', 'sub_input1']
    assert match.patrn2subj_op_map['input1'].name in ['sub_input0', 'sub_input1']
    assert match.patrn2subj_op_map['add0'].name == 'sub_add0'
    assert match.patrn2subj_op_map['output'].name == 'sub_add1'
