import matplotlib
matplotlib.use('Agg')
import theano
import theano.tensor as T
import lasagne
import argparse
import sys
import numpy as np
import pylab as plt
import os
from tqdm import tqdm


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--experiment", default='memnet',
                        help="Experiment name, the folder with all network definitions")
    parser.add_argument("--num_iter", type=int, default=100, help="Number of iterations")
    parser.add_argument("--batch_size", type=int, default=4, help='Size of minibatch')
    parser.add_argument("--obj_coef", default=1, type=float, help="Weight of objective loss")
    parser.add_argument("--cont_coef", default=1.0, type=float, help="Weight of content loss")
    parser.add_argument("--disc_coef", default=10.0,  type=float, help="Weight of discriminator")
    parser.add_argument("--disc_loss_mul", default=10.0,  type=float, help="Weight of discriminator")

    parser.add_argument("--tv_coef", default=3 * 1e-5, type=float, help="Weight of total variation")
    parser.add_argument("--num_img_to_show", default=5, help="Number of image to show")
    parser.add_argument("--experiment_folder", default='memnet/experiment-26',
                        help='Folder for saving plots and netowkrs in each iteration')
    parser.add_argument("--save_mode_it", default=5, help='Save model per this number of epoch')
    parser.add_argument("--device", default='gpu0', help='Which device to use')
    parser.add_argument("--dataset", default='datasets/nature-small', help='Folder with images for training')
    parser.add_argument("--cont_layer", default="conv3_1",
                        help='Take content features from this layer (input) for pixels')

    parser.add_argument("--num_layers_in_disc", default=4, type=int,
                        help="Number of layers in discriminator (1,2,3,4)")

    parser.add_argument("--learning_rate", default=0.001, type=float,
                        help='Learning rate')

    parser.add_argument("--loss_type_disc", default='log', help='Type of the loss function in discriminator (log, sqr)')

    return parser.parse_args()


def total_variation_loss(x):
    return (((x[:,:,:-1,:-1] - x[:,:,1:,:-1])**2 + (x[:,:,:-1,:-1] - x[:,:,:-1,1:])**2)**1.25).mean()


def compile(options):
    import content
    import discriminator
    import generator
    import objective

    input_to_generator = T.tensor4('img_with_noise', dtype='float32')
    input_to_content = T.tensor4('input_img', dtype='float32')
    input_to_discriminator = T.tensor4('true_img', dtype='float32')
    lr = theano.shared(np.array(options.learning_rate, dtype='float32'))
    obj_coef = theano.shared(np.array(options.obj_coef, dtype='float32'))

    G = generator.define_net()
    D = discriminator.define_patch_net(options.num_layers_in_disc)
    generated_img = lasagne.layers.get_output(G['out'], inputs=input_to_generator)

    objective_loss = obj_coef * objective.define_loss(generated_img).mean()
    content_loss = options.cont_coef * content.define_loss(input_to_content, generated_img, options.cont_layer).mean()
    disc_loss = options.disc_coef * discriminator.define_loss_generator(D, generated_img,
                                                input_to_discriminator, options.loss_type_disc).mean()
    tv_loss = options.tv_coef * total_variation_loss(generated_img)

    G_loss = (objective_loss +
              content_loss +
              disc_loss +
              tv_loss)

    D_params = lasagne.layers.get_all_params(D['out'], trainable=True)
    D_loss = options.disc_loss_mul *\
             discriminator.define_loss_discriminator(D, generated_img, input_to_discriminator, options.loss_type_disc)

    D_updates = lasagne.updates.adam(D_loss, D_params, learning_rate=lr)
    D_train_fn = theano.function([generated_img, input_to_discriminator], [D_loss],
                                 updates=D_updates, allow_input_downcast=True)

    G_params = lasagne.layers.get_all_params(G['out'], trainable=True)
    G_updates = lasagne.updates.adam(G_loss, G_params, learning_rate=lr)
    G_train_fn = theano.function([input_to_generator, input_to_content, input_to_discriminator],
                                 [generated_img, G_loss, objective_loss, content_loss, disc_loss, tv_loss],
                                 updates=G_updates, allow_input_downcast=True)
    generate_fn = theano.function([input_to_generator], generated_img, allow_input_downcast=True)
    return G_train_fn, D_train_fn, generate_fn, G, lr, obj_coef


def plot(options, epoch, images, generated_images):
    plt.clf()
    import util
    images = util.deprocess(images)
    generated_images = util.deprocess(generated_images)
    for i in range(len(images)):
        plt.subplot(len(images), 2, 2*i + 1)
        plt.axis('off')
        plt.imshow(images[i])
        plt.subplot(len(images), 2, 2*i + 2)
        plt.axis('off')
        plt.imshow(generated_images[i])
    plt.savefig(os.path.join(options.experiment_folder, 'plots', str(epoch) + '.png'), bbox_inches='tight')


def save_model(options, epoch, G):
    np.save(os.path.join(options.experiment_folder, 'model', 'generator-' + str(epoch) + '.npy'),
                lasagne.layers.get_all_param_values(G['out']))
    # np.save(os.path.join(options.experiment_folder, 'model', 'discriminator-' + str(epoch) + '.npy'),
    #             lasagne.layers.get_all_param_values(D['out']))


class ExperienceBuffer:
    def __init__(self, buffer_size, batch_shape):
        self.buffer = np.empty((buffer_size, batch_shape[1], batch_shape[2], batch_shape[3]))
        self.current_index = 0
        self.buffer_size = buffer_size
        self.batch_shape = batch_shape
        self.is_buffer_full = False

    def push_to_buffer(self, generated_imgs):
        for i in range(generated_imgs.shape[0]):
            self.current_index = (self.current_index + 1) % self.buffer_size
            self.is_buffer_full = self.is_buffer_full or self.current_index == 0
            self.buffer[self.current_index] = generated_imgs[i]

    def sample_mini_batch(self):
        high = self.buffer_size if self.is_buffer_full else self.current_index
        indexes = np.random.choice(high, size=self.batch_shape[0], replace=False)
        return self.buffer[indexes]


def train(options):
    print ("Compiling...")
    G_train_fn, D_train_fn, generate_fn, G, lr, obj_coef = compile(options)
    import util
    print ("Loading dataset...")
    X, _ = util.load_dataset(options.dataset, True)
    print ("Training...")
    log_file = open(os.path.join(options.experiment_folder, 'log.txt'), 'w')
    log_str = ("Experiment params: %s" % (options.__dict__, ))
    print(log_str)
    print(log_str, file=log_file)
    buffer = ExperienceBuffer(buffer_size=100, batch_shape=(options.batch_size, 3, 256, 256))
    for epoch in range(options.num_iter):
        # if (epoch + 1) % 20 == 0:
        #     lr.set_value(np.array(lr.get_value() * 0.3, dtype='float32'))

        # if (epoch + 1) % 3 == 0:
        #     obj_coef.set_value(np.array(obj_coef.get_value() + 0.1 * options.obj_coef, dtype='float32'))

        discriminator_order = np.arange(len(X))
        generator_order = np.arange(len(X))
        np.random.shuffle(discriminator_order)
        np.random.shuffle(generator_order)

        discriminator_loss_list = []
        generator_loss_list = []

        for start in tqdm(range(0, len(X), options.batch_size)):
            end = min(start + options.batch_size, len(X))

            generator_batch = util.preprocess(X[generator_order[start:end]])
            discriminator_batch = util.preprocess(X[discriminator_order[start:end]], True)

            generator_batch_with_noise = util.add_noise(generator_batch)

            #print (generate_fn(generator_batch_with_noise))
            generator_output = G_train_fn(generator_batch_with_noise, generator_batch, discriminator_batch)
            generated_batch, generator_loss = generator_output[0], generator_output[1:]
            #buffer.push_to_buffer(generator_batch)

            discriminator_loss = D_train_fn(generated_batch, discriminator_batch)

            discriminator_loss_list.append(discriminator_loss)
            generator_loss_list.append(generator_loss)

            log_str = (("Epoch %i" % epoch) + '\n'
                    + ("Discriminator loss %f" %
                            tuple(np.mean(np.array(discriminator_loss_list), axis=0))) + '\n'
                    + ("Generator loss %f, obj_loss %f, cont_loss %f, disc_loss %f, total_variation loss %f" %
                            tuple(np.mean(np.array(generator_loss_list), axis=0)))
                   )
            print(log_str)

        img_for_ploting = util.preprocess(X[0:options.num_img_to_show])
        plot(options, epoch, img_for_ploting, generate_fn(util.add_noise(img_for_ploting)))

        log_str = (("Epoch %i" % epoch) + '\n'
                    + ("Discriminator loss %f" %
                            tuple(np.mean(np.array(discriminator_loss_list), axis=0))) + '\n'
                    + ("Generator loss %f, obj_loss %f, cont_loss %f, disc_loss %f, total_variation loss %f" %
                            tuple(np.mean(np.array(generator_loss_list), axis=0)))
                   )
        print(log_str)
        print(log_str, file=log_file)
        if epoch % options.save_mode_it == 0:
            save_model(options, epoch, G)
        log_file.flush()

    log_file.close()
    save_model(options, options.num_iter - 1, G)

    return G


def main():
    options = parse_args()
    import theano.sandbox.cuda
    theano.sandbox.cuda.use(options.device)
    plt.rcParams['image.cmap'] = 'gray'
    if not os.path.exists(options.experiment_folder):
        os.mkdir(options.experiment_folder)
    if not os.path.exists(os.path.join(options.experiment_folder, 'model')):
        os.mkdir(os.path.join(options.experiment_folder, 'model'))
    if not os.path.exists(os.path.join(options.experiment_folder, 'plots')):
        os.mkdir(os.path.join(options.experiment_folder, 'plots'))
    sys.path.insert(0, options.experiment)
    _ = train(options)

if __name__ == "__main__":
    main()
