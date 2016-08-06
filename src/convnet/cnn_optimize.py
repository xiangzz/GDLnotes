from __future__ import print_function


from convnet.conv_mnist import maxpool2d, load_reformat_not_mnist
from neural.full_connect import accuracy
from util.request import fit_loss, better_hyper

import tensorflow as tf


def up_div(y, x):
    if y % x > 0:
        return y / x + 1
    else:
        return y / x


def size_by_conv(stride_ps, data_size, total_layer_cnt):
    param1 = data_size[1]
    param2 = data_size[2]
    for i in range(total_layer_cnt):
        param1 = up_div(param1, stride_ps[i][1])
        param1 = up_div(param1, 2)
        param2 = up_div(param2, stride_ps[i][2])
        param2 = up_div(param2, 2)
    return param1 * param2 * data_size[0]


def conv_train(basic_hps, stride_ps, layer_cnt=3, drop=False, lrd=False):
    batch_size = basic_hps['batch_size']
    patch_size = basic_hps['patch_size']
    depth = basic_hps['depth']
    num_hidden = basic_hps['num_hidden']
    num_channels = basic_hps['num_channels']
    loss_collect = list()

    graph = tf.Graph()
    with graph.as_default():
        # Input data.
        tf_train_dataset = tf.placeholder(
            tf.float32, shape=(batch_size, image_size, image_size, num_channels))
        tf_train_labels = tf.placeholder(tf.float32, shape=(batch_size, num_labels))
        tf_valid_dataset = tf.constant(valid_dataset)
        tf_test_dataset = tf.constant(test_dataset)

        # Variables.
        input_weights = tf.Variable(tf.truncated_normal(
            [patch_size, patch_size, num_channels, depth], stddev=0.1))
        input_biases = tf.Variable(tf.zeros([depth]))

        mid_layer_cnt = layer_cnt - 1
        layer_weights = list()
        layer_biases = [tf.Variable(tf.constant(1.0, shape=[depth])) for _ in range(mid_layer_cnt)]
        output_weights = list()
        output_biases = tf.Variable(tf.constant(1.0, shape=[num_hidden]))
        final_weights = tf.Variable(tf.truncated_normal(
            [num_hidden, num_labels], stddev=0.1))
        final_biases = tf.Variable(tf.constant(1.0, shape=[num_labels]))
        weight_set_done = False

        # Model.
        def model(data):
            conv = tf.nn.conv2d(data, input_weights, stride_ps[0], use_cudnn_on_gpu=True, padding='SAME')
            conv = maxpool2d(conv)
            hidden = tf.nn.relu(conv + input_biases)
            if drop:
                hidden = tf.nn.dropout(hidden, 0.5)
            for i in range(mid_layer_cnt):
                print(hidden)
                if not weight_set_done:
                    layer_weight = tf.Variable(tf.truncated_normal(
                        [patch_size / (i + 1), patch_size / (i + 1), depth, depth], stddev=0.1))
                    layer_weights.append(layer_weight)
                conv = tf.nn.conv2d(hidden, layer_weights[i], stride_ps[i + 1], use_cudnn_on_gpu=True, padding='SAME')
                conv = maxpool2d(conv)
                hidden = tf.nn.relu(conv + layer_biases[i])
                if drop:
                    hidden = tf.nn.dropout(hidden, 0.7)

            shapes = hidden.get_shape().as_list()
            shape_mul = 1
            for s in shapes[1:]:
                shape_mul *= s

            if not weight_set_done:
                output_size = shape_mul
                output_weights.append(tf.Variable(tf.truncated_normal([output_size, num_hidden], stddev=0.1)))
            reshape = tf.reshape(hidden, [shapes[0], shape_mul])

            hidden = tf.nn.relu(tf.matmul(reshape, output_weights[0]) + output_biases)
            if drop:
                hidden = tf.nn.dropout(hidden, 0.8)
            return tf.matmul(hidden, final_weights) + final_biases

        # Training computation.
        logits = model(tf_train_dataset)
        loss = tf.reduce_mean(
            tf.nn.softmax_cross_entropy_with_logits(logits, tf_train_labels))
        # Optimizer.
        if lrd:
            cur_step = tf.Variable(0)  # count the number of steps taken.
            starter_learning_rate = 0.1
            learning_rate = tf.train.exponential_decay(starter_learning_rate, cur_step, 10000, 0.96, staircase=True)
            optimizer = tf.train.GradientDescentOptimizer(learning_rate).minimize(loss, global_step=cur_step)
        else:
            optimizer = tf.train.GradientDescentOptimizer(0.05).minimize(loss)

        # Predictions for the training, validation, and test data.
        train_prediction = tf.nn.softmax(logits)
        valid_prediction = tf.nn.softmax(model(tf_valid_dataset))
        test_prediction = tf.nn.softmax(model(tf_test_dataset))
    num_steps = 3001
    start_fit = 550
    init_loss = []

    with tf.Session(graph=graph) as session:
        tf.initialize_all_variables().run()
        print('Initialized')
        end_train = False
        mean_loss = 0
        for step in range(num_steps):
            if end_train:
                break
            offset = (step * batch_size) % (train_labels.shape[0] - batch_size)
            batch_data = train_dataset[offset:(offset + batch_size), :, :, :]
            batch_labels = train_labels[offset:(offset + batch_size), :]
            feed_dict = {tf_train_dataset: batch_data, tf_train_labels: batch_labels}
            _, l, predictions = session.run(
                [optimizer, loss, train_prediction], feed_dict=feed_dict)
            mean_loss += l
            if step % 5 == 0:
                mean_loss /= 5.0
                loss_collect.append(mean_loss)
                mean_loss = 0
                if step >= start_fit:
                    # print(loss_collect)
                    res = fit_loss(
                        [batch_size / 100.0, depth / 100.0, num_hidden / 100.0, layer_sum / 100.0, patch_size / 100.0],
                        loss_collect)
                    loss_collect.remove(loss_collect[0])
                    ret = res['ret']
                    if ret == 1:
                        print('ret is end train when step is {step}'.format(step=step))
                        init_loss.append(loss_collect)
                        end_train = True

            if step % 50 == 0:
                print('Minibatch loss at step %d: %f' % (step, l))
                print('Minibatch accuracy: %.1f%%' % accuracy(predictions, batch_labels))
                print('Validation accuracy: %.1f%%' % accuracy(
                    valid_prediction.eval(), valid_labels))

        print('Test accuracy: %.1f%%' % accuracy(test_prediction.eval(), test_labels))
        if end_train:
            better_hyper(
                [batch_size / 100.0, depth / 100.0, num_hidden / 100.0, layer_sum / 100.0, patch_size / 100.0], init_loss[0])
    for loss in loss_collect:
        print(loss)


if __name__ == '__main__':
    image_size = 28
    num_labels = 10
    train_dataset, train_labels, valid_dataset, valid_labels, test_dataset, test_labels = \
        load_reformat_not_mnist(image_size, num_labels, 1)
    pick_size = 2048
    valid_dataset = valid_dataset[0: pick_size, :, :, :]
    valid_labels = valid_labels[0: pick_size, :]
    test_dataset = test_dataset[0: pick_size, :, :, :]
    test_labels = test_labels[0: pick_size, :]
    basic_hypers = {
        'batch_size': 16,
        'patch_size': 5,
        'depth': 16,
        'num_hidden': 64,
        'num_channels': 1,
    }
    layer_sum = 3
    stride_params = [[1, 1, 1, 1] for _ in range(layer_sum)]
    conv_train(basic_hypers, stride_params, layer_cnt=layer_sum, lrd=True)
