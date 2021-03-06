import lasagne

def define_net():
	net = {}
	net['input'] = lasagne.layers.InputLayer(shape = (None, 1, 28, 28))
	net['conv_1'] = lasagne.layers.Conv2DLayer(net['input'], num_filters = 32, filter_size = (5, 5))
	net['pool_1'] = lasagne.layers.MaxPool2DLayer(net['conv_1'], pool_size = (2,2))
	net['conv_2'] = lasagne.layers.Conv2DLayer(net['pool_1'], num_filters = 64, filter_size = (5,5))
	net['pool_2'] = lasagne.layers.MaxPool2DLayer(net['conv_2'], pool_size = (2,2))

	net['fc3'] = lasagne.layers.DenseLayer(net['pool_2'], num_units = 1024)
	net['dp3'] = lasagne.layers.dropout(net['fc3'])

	net['fc4'] = lasagne.layers.DenseLayer(net['dp3'], num_units = 256)
	net['dp4'] = lasagne.layers.dropout(net['fc4'])
	net['out'] = lasagne.layers.DenseLayer(net['dp4'], num_units = 1, nonlinearity = lasagne.nonlinearities.sigmoid)

	return net


