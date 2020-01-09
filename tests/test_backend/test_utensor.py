import os

def test_utensor(mlp_ugraph):
    from utensor_cgen.backend.utensor import uTensorBackend

    this_dir = os.path.dirname(__file__)

    uTensorBackend(config={
        'utensor': {
            'backend': {
                'code_generator': {
                    'model_dir': os.path.join(this_dir, 'models'),
                    'params_dir': os.path.join(this_dir, 'data'),
                },
                'graph_lower': {}
            },
        }
    }).apply(mlp_ugraph)
