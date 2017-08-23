''' Variational Autoencoder based tumor subpopulation detection
    author: Sabrina Rashid 
'''
import sys
import numpy as np
import matplotlib.pyplot as plt
import scipy
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn import mixture
from keras.layers import Input, Dense, Lambda, Layer
from keras.models import Model
from keras import backend as K
from keras import metrics, optimizers
from mpl_toolkits.mplot3d import Axes3D
import operator


def my_except_hook(exctype, value, traceback):
        print('There has been an error in the system')
sys.excepthook = my_except_hook

def main(input_datafile='Synthetic_data_2500.mat',latent_dim=3,
         N_starts=5,batch_size=100,learning_rate=.0001, epochs = 10,
         clip_norm=2,output_datafile='output',to_cluster= 1,n_genes=5000,
         gene_selection=0,selection_criteria='average',to_plot=1,verbose=0,
         relative_expression=0):
    
    ## check value inputs
    
    # read datafile    
    dict=scipy.io.loadmat(input_datafile)
    x_t=dict['syn_expr'] # input expression matrix # of cells * # of genes
    x_t[np.isnan(x_t)]=0
    size=x_t.shape
    
    
    # gene selection
    if gene_selection:
        a=[0 for i in range(size[1])]
        cv=[0 for i in range(size[1])]
        en=[0 for i in range(size[1])]
        for i in range(0,size[1]):
            cv[i]=np.std(x_t[:,i])/np.mean(x_t[:,i]) # CV criteria
            a[i]=np.mean(x_t[:,i]) # average value
            hist, bin_edges=np.histogram(x_t[:,i],bins=100)
            pk=hist/sum(hist)
            en[i]=scipy.stats.entropy(pk)    # entropy        
        if selection_criteria=='average':
            sorted_indices=sorted(range(len(a)), key=lambda k: a[k])
        elif selection_criteria == 'cv':
            sorted_indices=sorted(range(len(cv)), key=lambda k: cv[k])
        elif selection_criteria == 'entropy':
            sorted_indices=sorted(range(len(en)), key=lambda k: en[k])            
        else:
            print('Not a valid selection criteria, Refer to the readme file for valid selection criteria')
            
        x_t=x_t[:,sorted_indices[0:min(n_genes,size[1])]]
    
    if relative_expression:
        x_t=x_t-np.mean(x_t,axis=1)
        
    x_train=x_t   
    size=x_train.shape
    
    # pad end cells for being compatible with batch size
    reminder=size[0]%batch_size
    x_train=np.concatenate((x_train,x_train[(size[0]-reminder):size[0],:]),axis=0)

    # internal parameters
    original_dim = size[1]
    epsilon_std = 1.0
    n_clusters=6
    intermediate_deep_dim=1024
    intermediate_deep_dim2=512
    intermediate_dim = 256
    color_iter = ['navy', 'turquoise', 'cornflowerblue','darkorange','mistyrose','seagreen','hotpink','purple','thistle','darkslategray']
    
    # required initializations
    silhouette_avg=[0 for i in range(N_starts)]
    all_x_encoded = np.asarray([[[0 for k in range(latent_dim)] for j in range(size[0])] for i in range(N_starts)])
    all_x_encoded = all_x_encoded.astype(float)
    
    def sampling(args):
        z_mean, z_log_var = args
        epsilon = K.random_normal(shape=(batch_size, latent_dim), mean=0.,
                                  stddev=epsilon_std)
        return z_mean + K.exp(z_log_var / 2) * epsilon
    
    
    
    # Custom loss layer
    class CustomVariationalLayer(Layer):
        def __init__(self, **kwargs):
            self.is_placeholder = True
            super(CustomVariationalLayer, self).__init__(**kwargs)
    
        def vae_loss(self, x, x_decoded_mean):
            xent_loss =  original_dim * metrics.binary_crossentropy(x, x_decoded_mean) 
            kl_loss = - 0.5 * K.sum(1 + z_log_var - K.square(z_mean) - K.exp(z_log_var), axis=-1)
            
            return K.mean(xent_loss + kl_loss)
    
        def call(self, inputs):
            x = inputs[0]
            x_decoded_mean = inputs[1]
            loss = self.vae_loss(x, x_decoded_mean)            
            self.add_loss(loss, inputs=inputs)
            return x
        
        
        
    for i in range(0,N_starts):
    
        x = Input(batch_shape=(batch_size, original_dim))
        e = Dense(intermediate_deep_dim, activation = 'relu')(x)
        d= Dense(intermediate_deep_dim2, activation ='relu')(e)
        h = Dense(intermediate_dim, activation='relu')(d)
    
        z_mean = Dense(latent_dim)(h)
        z_log_var = Dense(latent_dim)(h)

        # note that "output_shape" isn't necessary with the TensorFlow backend
        z = Lambda(sampling, output_shape=(latent_dim,))([z_mean, z_log_var])

        # we instantiate these layers separately so as to reuse them later
        decoder_h = Dense(intermediate_dim, activation='relu')
        decoder_d = Dense(intermediate_deep_dim2, activation ='relu')
        decoder_e = Dense(intermediate_deep_dim, activation = 'relu')
        decoder_mean = Dense(original_dim, activation='sigmoid')
        h_decoded = decoder_h(z)
        d_decoded = decoder_d(h_decoded)
        e_decoded = decoder_e(d_decoded)
        x_decoded_mean = decoder_mean(e_decoded)

        y = CustomVariationalLayer()([x, x_decoded_mean])
        vae = Model(x, y)
        rmsprop = optimizers.rmsprop(lr=learning_rate,clipnorm=clip_norm)
        vae.compile(optimizer=rmsprop, loss=None)
    
    
        vae.fit(x_train,
                shuffle=True,
                epochs=epochs,
                batch_size=batch_size,
                verbose=verbose)
    
    
        # build a model to project inputs on the latent space
        encoder = Model(x, z_mean)
        x_encoded = encoder.predict(x_train, batch_size=batch_size)
        if np.isnan(x_encoded).any():
           # x_encoded=np.asarray([[0 for j in range(latent_dim)] for i in range(size[0])])
            silhouette_avg[i]=0
        else:
            clusterer = KMeans(n_clusters=n_clusters, random_state=10)
            cluster_labels = clusterer.fit_predict(x_encoded)
            silhouette_avg[i] = silhouette_score(x_encoded, cluster_labels)

        all_x_encoded[i][:][:]=x_encoded
        

    index, value = max(enumerate(silhouette_avg), key=operator.itemgetter(1))
    x_encoded_final=all_x_encoded[index][:][:]
    x_encoded_final=x_encoded_final[0:size[0],:]
    
    if np.isnan(x_encoded_final).any():
        print('NaNs, check input, learning rate, clip_norm parameters')
    
    if to_plot:
        if latent_dim>=3:
            fig=plt.figure(figsize=(6, 6))
            ax3D = fig.add_subplot(111, projection='3d')
            ax3D.scatter(x_encoded_final[:, 0], x_encoded_final[:, 1], x_encoded_final[:, 2])
            ax3D.set_xlabel('Latent dim 1')
            ax3D.set_ylabel('Latent dim 2')   
            ax3D.set_zlabel('Latent dim 3')            
            plt.savefig(output_datafile+'fig_projection.png')
        elif latent_dim==2:
            fig=plt.figure(figsize=(6, 6))
            plt.scatter(x_encoded_final[:, 0], x_encoded_final[:, 1])
            plt.xlabel('Latent dim 1')
            plt.ylabel('Latent dim 2') 
            plt.savefig(output_datafile+'fig_projection.png')
        
    if to_cluster:
        n_components_range = range(1, 10)
        bic = []
        for n_components in n_components_range:
            gmm = mixture.GaussianMixture(n_components=n_components, covariance_type='tied',n_init=10)
            gmm.fit(x_encoded_final)
            bic.append(gmm.bic(x_encoded_final))
    
        bic = np.array(bic)+np.log(size[0])*n_components_range*latent_dim
        ind,val=min(enumerate(bic), key=operator.itemgetter(1))
        if to_plot:
            fig=plt.figure(figsize=(6, 6))
            plt.plot(n_components_range,bic)
            plt.xlabel('Number of clusters')
            plt.ylabel('BIC')
            plt.savefig(output_datafile+'fig_bic.png')
    
        gmm = mixture.GaussianMixture(n_components=ind+1, covariance_type='tied')
        gmm.fit(x_encoded_final)
        labels=gmm.predict(x_encoded_final)
        
        if to_plot:
            if latent_dim>=3:
                fig=plt.figure()
                ax3D = fig.add_subplot(111, axisbg="1.0",projection='3d')        
                for i in range(0,labels.max()+1):
                    ax3D.scatter(x_encoded_final[labels==i, 0], x_encoded_final[labels==i, 1], x_encoded_final[labels==i, 2],alpha=1, color=color_iter[i])
                    ax3D.set_xlabel('Latent dim 1')
                    ax3D.set_ylabel('Latent dim 2')   
                    ax3D.set_zlabel('Latent dim 3')
                    plt.savefig(output_datafile+'fig_cluster.png')

            elif latent_dim==2:
                fig=plt.figure()
                for i in range(0,labels.max()+1):
                    plt.scatter(x_encoded_final[labels==i, 0], x_encoded_final[labels==i, 1],alpha=1, color=color_iter[i])
                    plt.xlabel('Latent dim 1')
                    plt.ylabel('Latent dim 2') 
                    plt.savefig(output_datafile+'fig_cluster.png')
        
        scipy.io.savemat(output_datafile+'.mat', {'vect':x_encoded_final,'labels':labels,'bic':bic})
    
    else:
        scipy.io.savemat(output_datafile+'.mat', {'vect':x_encoded_final})