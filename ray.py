import numpy as np
from my_siddon import *
from object import *
from jones import *

magnObj = 60
nrCamPix = 16 # num pixels behind lenslet
camPixPitch = 6.5
microLensPitch = nrCamPix * camPixPitch / magnObj
voxPitch = microLensPitch / 5

'''The number of voxels along each side length of the cube is determined by the voxPitch. 
An odd number of voxels will allow the center of a voxel in the center of object space.
Object space center:
    - voxCtr:center voxel where all rays of the central microlens converge
    - volCtr:same center in micrometers'''

voxNrX = round(250/voxPitch)
if voxNrX % 2 == 1:
    voxNrX += 1
voxNrYZ = round(700/voxPitch)
if voxNrYZ % 2 == 1:
    voxNrYZ += 1
voxCtr = np.array([voxNrX/2, voxNrYZ/2, voxNrYZ/2])
volCtr = voxCtr * voxPitch

wavelength = 0.550
naObj = 1.2
nMedium = 1.52

set_wavelength(wavelength)

def main():
    '''Finding angles to/between central lenset, which is the angle going to each 
    of the 16 pixels for each microlens.'''

    microLensCtr = [8, 8] # (unit: camera pixels)
    rNA = 7.5 # radius of edge of microlens lens (unit:camera pixels), 
                # can be measured in back focal plane of microlenses
    camPixRays = np.zeros([nrCamPix, nrCamPix])
    i = np.linspace(1, nrCamPix, nrCamPix)
    j = np.linspace(1, nrCamPix, nrCamPix)
    jv, iv = np.meshgrid(i, j) # row/column defined instead of by coordinate
    distFromCtr = np.sqrt((iv-0.5-microLensCtr[0])**2 + (jv-0.5-microLensCtr[1])**2)
    camPixRays[distFromCtr > rNA] = np.NaN
    iRel2Ctr = iv-0.5-microLensCtr[0]
    jRel2Ctr = jv-0.5-microLensCtr[1]
    camPixRaysAzim = np.round(np.rad2deg(np.arctan2(jRel2Ctr, iRel2Ctr)))
    camPixRaysAzim[distFromCtr > rNA] = np.NaN
    distFromCtr[distFromCtr > rNA] = np.NaN
    camPixRaysTilt = np.round(np.rad2deg(np.arcsin(distFromCtr/rNA*naObj/nMedium)))

    '''Camera ray entrance. For each inital ray position, we find the position on the 
    entrance face of the object cube for which the ray enters.
    This is bascially the same as "rayEnter". Here x=0.'''
    camRayEntranceX = np.zeros([nrCamPix, nrCamPix])
    camRayEntranceY = volCtr[0]*np.tan(np.deg2rad(camPixRaysTilt))*np.sin(np.deg2rad(camPixRaysAzim))+volCtr[1]
    camRayEntranceZ = volCtr[0]*np.tan(np.deg2rad(camPixRaysTilt))*np.cos(np.deg2rad(camPixRaysAzim))+volCtr[2]
    camRayEntranceX[np.isnan(camRayEntranceY)] = np.NaN
    nrRays = np.sum(~np.isnan(camRayEntranceY)) # Number of all rays in use
    camRayEntrance = np.array([camRayEntranceX, camRayEntranceY, camRayEntranceZ])
    rayEnter = camRayEntrance.copy()
    volCtrGridTemp = np.array([np.full((nrCamPix,nrCamPix), volCtr[i]) for i in range(3)])
    rayExit = rayEnter + 2 * (volCtrGridTemp - rayEnter)

    '''Direction of the rays at the exit plane'''
    rayDiff = rayExit - rayEnter
    rayDiff = rayDiff / np.linalg.norm(rayDiff, axis=0)

    '''For the (i,j) pixel behind a single microlens'''
    i = 3
    j = 8
    start = rayEnter[:,i,j]
    stop = rayExit[:,i,j]
    siddon_list = siddon_params(start, stop, [voxPitch]*3, [voxNrX, voxNrYZ, voxNrYZ])
    seg_mids = siddon_midpoints(start, stop, siddon_list)
    voxels_of_segs = vox_indices(seg_mids, [voxPitch]*3)
    ell_in_voxels = siddon_lengths(start, stop, siddon_list)

    ray = rayDiff[:,i,j]
    rayDir = calc_rayDir(ray)
    JM_list = []
    for m in range(len(ell_in_voxels)):
        ell = ell_in_voxels[m]
        vox = voxels_of_segs[m]
        Delta_n, opticAxis = get_ellipsoid(vox)
        JM = voxRayJM(Delta_n, opticAxis, rayDir, ell)
        JM_list.append(JM)
    effective_JM = rayJM(JM_list)
    print(f"Effective Jones matrix for the ray hitting pixel {i, j}: {effective_JM}")

if __name__ == '__main__':
    main()
    