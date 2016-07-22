import numpy as np
from scipy.special import jv # Bessel Function of the first kind
from scipy.linalg import eig
from scipy.fftpack import fftn, ifftn, ifft
import progressbar
from scipy.ndimage import filters as fi
import math

# An implementation of the Optimally Oriented 
# M.W.K. Law and A.C.S. Chung, ``Three Dimensional Curvilinear 
# Structure Detection using Optimally Oriented Flux'', ECCV 2008, pp.
# 368--382.
# Max W. K. Law et al., ``Dilated Divergence based Scale-Space 
# Representation for Curve Analysis'', ECCV 2012, pp. 557--571.
# Author: Siqi Liu

def bgresponse(img, radii, rho):
    eps = 1e-12
    rsp = np.zeros(img.shape)
    bar = progressbar.ProgressBar(max_value=radii.size)

    for i, tensorfield in enumerate(bgtensor(img, radii, rho)):
        eig1, eig2, eig3 = eigval33(tensorfield)
        maxe = eig1 - eps
        mine = eig1 - eps
        sume = maxe + eig2 + eig3
        del eig1

        cond = np.abs(eig2) > np.abs(maxe)
        maxe[cond] = eig2[cond]

        cond = np.abs(eig2) < np.abs(mine)
        mine[cond] = eig2[cond]
        del eig2

        cond = np.abs(eig3) > np.abs(maxe)
        maxe[cond] = eig3[cond]

        cond = np.abs(eig3) < np.abs(mine)
        mine[cond] = eig3[cond]
        del eig3

        mide = sume - maxe - mine;

        cond = sume >= 0
        feat = -mide / maxe * (mide + maxe) # Medialness measure response
        del mine
        del maxe
        del mide
        del sume
        feat[cond] = 0 # Filter the non-anisotropic voxels
        cond = np.abs(feat) > np.abs(rsp)
        rsp[cond] = feat[cond]
        bar.update(i+1)
        del tensorfield
        del feat
        del cond
    return rsp


def eigsparse3(tensorfield, lidx):
    f11, f12, f13, f22, f23, f33 = tensorfield
    eigvals = np.zeros(lidx.shape[0], 3)
    eigvecs = np.zeros(lidx.shape[0], 3, 3)

    for i, idx in enumerate(lidx):
        tensor = np.asarray([[f11[idx[0], idx[1], idx[2]], f12[idx[0], idx[1], idx[2]], f13[idx[0], idx[1], idx[2]]],
                             [f12[idx[0], idx[1], idx[2]], f22[idx[0], idx[1], idx[2]], f23[idx[0], idx[1], idx[2]]],
                             [f13[idx[0], idx[1], idx[2]], f23[idx[0], idx[1], idx[2]], f33[idx[0], idx[1], idx[2]]]])
        w, v = np.linalg.eig(tensor)
        eigvals[i, :] = w
        eigvecs[i, :, :] = v 
    return eigvecs, eigvals


def oofresponse(img, radii, memory_save=True):
    rsp = np.zeros(img.shape)
    bar = progressbar.ProgressBar(max_value=radii.size)

    for i,tensorfield in enumerate(ooftensor(img, radii, memory_save)):
        eig1, eig2, eig3 = eigval33(tensorfield)
        maxe = eig1
        mine = eig1
        sume = maxe + eig2 + eig3   
        cond = np.abs(eig2) > np.abs(maxe)
        maxe[cond] = eig2[cond]
        cond = np.abs(eig2) < np.abs(mine)
        mine[cond] = eig2[cond]
        cond = np.abs(eig3) > np.abs(maxe)
        maxe[cond] = eig3[cond]
        cond = np.abs(eig3) < np.abs(mine)
        mine[cond] = eig3[cond]
        mide = sume - maxe - mine;
        feat = maxe
        cond = np.abs(feat) > np.abs(rsp)
        rsp[cond] = feat[cond]
        bar.update(i+1)

    return rsp


def bgkern3(kerlen, mu=0, sigma=3., rho=0.2):
    '''
    Generate the bi-gaussian kernel
    '''
    sigma_b = rho * sigma
    k = rho ** 2
    kr = (kerlen - 1) / 2 
    X, Y, Z = np.meshgrid(np.arange(-kr, kr+1),
                          np.arange(-kr, kr+1), 
                          np.arange(-kr, kr+1))
    dist = np.linalg.norm(np.stack((X, Y, Z)), axis=0) 

    G  = gkern3(dist, mu, sigma) # Normal Gaussian with mean at origin
    Gb = gkern3(dist, sigma-sigma_b, sigma_b)

    c0 = k * Gb[0, 0, math.floor(sigma_b)] - G[0, 0, math.floor(sigma)]
    c1 = G[0, 0, math.floor(sigma)] - k * Gb[0, 0, math.floor(sigma_b)] + c0
    G += c0
    Gb = k * Gb + c1 # Inverse Gaussian with phase shift

    # Replace the centre of Gb with G
    central_region = dist <= sigma
    del dist
    X = (X[central_region] + kr).astype('int')
    Y = (Y[central_region] + kr).astype('int')
    Z = (Z[central_region] + kr).astype('int')
    Gb[X, Y, Z] = G[X, Y, Z]

    return Gb


def gkern3(dist, mu=0., sigma=3.):
    '''
    Make 3D gaussian kernel
    '''
    # Make a dirac spherical function
    return np.exp(-0.5 * (((dist - mu) / sigma)**2)) / (sigma * np.sqrt(2. * np.pi))


def hessian3(x):
    """
    Calculate the hessian matrix with finite differences
    Parameters:
       - x : ndarray
    Returns:
       an array of shape (x.dim, x.ndim) + x.shape
       where the array[i, j, ...] corresponds to the second derivative x_ij
    """
    x_grad = np.gradient(x)
    tmpgrad = np.gradient(x_grad[0])
    f11 = tmpgrad[0]
    f12 = tmpgrad[1]
    f13 = tmpgrad[2]
    tmpgrad = np.gradient(x_grad[1])
    f22 = tmpgrad[1]
    f23 = tmpgrad[2]
    tmpgrad = np.gradient(x_grad[2])
    f33 = tmpgrad[2]
    return [f11, f12, f13, f22, f23, f33]


def bgtensor(img, lsigma, rho=0.2):
    eps = 1e-12
    fimg = fftn(img, overwrite_x=True)

    for s in lsigma:
        jvbuffer = bgkern3(kerlen=math.ceil(s)*6+1, sigma=s, rho=rho)
        jvbuffer = fftn(jvbuffer, shape=fimg.shape, overwrite_x=True) * fimg
        fimg = ifftn(jvbuffer, overwrite_x=True)
        yield hessian3(np.real(fimg))


def eigval33(tensorfield):
    ''' Calculate the eigenvalues of massive 3x3 real symmetric matrices. '''
    a11, a12, a13, a22, a23, a33 = tensorfield  
    eps = 1e-50
    b = a11 + eps
    d = a22 + eps
    j = a33 + eps
    c = - a12**2. - a13**2. - a23**2. + b * d + d * j + j* b 
    d = - b * d * j + a23**2. * b + a12**2. * j - a13**2. * d + 2. * a13 * a12 * a23
    b = - a11 - a22 - a33 - 3. * eps 
    d = d + (2. * b**3. - 9. * b * c) / 27

    c = b**2. / 3. - c
    c = c**3.
    c = c / 27
    c[c < 0] = 0
    c = np.sqrt(c)

    j = c ** (1./3.) 
    c = c + (c==0).astype('float')
    d = -d /2. /c
    d[d>1] = 1
    d[d<-1] = 1
    d = np.real(np.arccos(d) / 3.)
    c = j * np.cos(d)
    d = j * np.sqrt(3.) * np.sin(d)
    b = -b / 3.

    j = -c - d + b
    d = -c + d + b
    b = 2. * c + b

    return b, j, d


def oofftkernel(kernel_radius, r, sigma=1, ntype=1):
    eps = 1e-12
    normalisation = 4/3 * np.pi * r**3 / (jv(1.5, 2*np.pi*r*eps) / eps ** (3/2)) / r**2 *  \
                    (r / np.sqrt(2.*r*sigma - sigma**2)) ** ntype
    jvbuffer = normalisation * np.exp( (-2 * sigma**2 * np.pi**2 * kernel_radius**2) / (kernel_radius**(3/2) ))
    return (np.sin(2 * np.pi * r * kernel_radius) / (2 * np.pi * r * kernel_radius) - np.cos(2 * np.pi * r * kernel_radius)) * \
               jvbuffer * np.sqrt( 1./ (np.pi**2 * r *kernel_radius ))


def ooftensor(img, radii, memory_save=True):
    '''
    type: oof, bg
    '''
    # sigma = 1 # TODO: Pixel spacing
    eps = 1e-12
    # ntype = 1 # The type of normalisation
    fimg = fftn(img, overwrite_x=True)
    shiftmat = ifftshiftedcoormatrix(fimg.shape)
    x, y, z = shiftmat
    x = x / fimg.shape[0]
    y = y / fimg.shape[1]
    z = z / fimg.shape[2]
    kernel_radius = np.sqrt(x ** 2 + y ** 2 + z ** 2) + eps # The distance from origin

    for r in radii:
        # Make the fourier convolutional kernel
        jvbuffer = oofftkernel(kernel_radius, r) * fimg

        if memory_save:
            # F11
            buffer = ifftshiftedcoordinate(img.shape, 0) ** 2 * x * x * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f11 = buffer.copy()

            # F12
            buffer = ifftshiftedcoordinate(img.shape, 0) * ifftshiftedcoordinate(img.shape, 1) * x * y * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f12 = buffer.copy()

            # F13
            buffer = ifftshiftedcoordinate(img.shape, 0) * ifftshiftedcoordinate(img.shape, 2) * x * z * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f13 = buffer.copy()

            # F22
            buffer = ifftshiftedcoordinate(img.shape, 1) ** 2 * y ** 2 * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f22 = buffer.copy()

            # F23
            buffer = ifftshiftedcoordinate(img.shape, 1) * ifftshiftedcoordinate(img.shape, 2) * y * z * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f23 = buffer.copy()

            # F33
            buffer = ifftshiftedcoordinate(img.shape, 2) * ifftshiftedcoordinate(img.shape, 2) * z * z * jvbuffer
            buffer = ifft(buffer, axis=0)
            buffer = ifft(buffer, axis=1)
            buffer = ifft(buffer, axis=2)
            f33 = buffer.copy()
        else:
            f11 = np.real(ifftn(x * x * jvbuffer))
            f12 = np.real(ifftn(x * y * jvbuffer))
            f13 = np.real(ifftn(x * z * jvbuffer))
            f22 = np.real(ifftn(y * y * jvbuffer))
            f23 = np.real(ifftn(y * z * jvbuffer))
            f33 = np.real(ifftn(z * z * jvbuffer))
        yield [f11, f12, f13, f22, f23, f33]


# The dimension is a vector specifying the size of the returned coordinate
# matrices. The number of output argument is equals to the dimensionality
# of the vector "dimension". All the dimension is starting from "1"
def ifftshiftedcoormatrix(shape):
    shape = np.asarray(shape)
    p = np.floor(np.asarray(shape) / 2).astype('int')
    coord = []
    for i in range(shape.size):
        a = np.hstack((np.arange(p[i], shape[i]), np.arange(0, p[i]))) - p[i] - 1.
        repmatpara = np.ones((shape.size,)).astype('int')
        repmatpara[i] = shape[i]
        A = a.reshape(repmatpara)
        repmatpara = shape.copy()
        repmatpara[i] = 1
        coord.append(np.tile(A, repmatpara))

    return coord


def ifftshiftedcoordinate(shape, axis):
    shape = np.asarray(shape)
    p = np.floor(np.asarray(shape) / 2).astype('int')
    a = (np.hstack((np.arange(p[axis], shape[axis]), np.arange(0, p[axis]))) - p[axis] - 1.).astype('float')
    a /= shape[axis].astype('float')
    reshapepara = np.ones((shape.size,)).astype('float');
    reshapepara[axis] = shape[axis];
    A = a.reshape(reshapepara);
    repmatpara = shape.copy();
    repmatpara[axis] = 1;
    return np.tile(A, repmatpara)


def nonmaximal_suppression3(img, radii, threshold=0, radius):
    '''
    Non-maximal suppression with oof eigen vector
    '''
