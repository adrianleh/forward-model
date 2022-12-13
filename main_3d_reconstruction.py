"""Main script to run 3D reconstruction
- includes forward projection
"""
import time
import os
import torch
from tqdm import tqdm
from waveblocks.utils.misc_utils import *
from VolumeRaytraceLFM.abstract_classes import BackEnds
from VolumeRaytraceLFM.birefringence_implementations import BirefringentVolume, BirefringentRaytraceLFM

# Select backend: requires pytorch to calculate gradients
backend = BackEnds.PYTORCH

# Get optical parameters template
optical_info = BirefringentVolume.get_optical_info_template()
# Alter some of the optical parameters
optical_info['volume_shape'] = [11,51,51]
optical_info['axial_voxel_size_um'] = 1.0
optical_info['pixels_per_ml'] = 17
optical_info['n_micro_lenses'] = 21
optical_info['n_voxels_per_ml'] = 1

training_params = {
    'n_epochs' : 5000,
    'azimuth_weight' : 1,
    'lr' : 1e-2,
    'output_posfix' : '11ml_atan2loss'
}


# Volume type
# number is the shift from the end of the volume, change it as you wish,
#   do single_voxel{volume_shape[0]//2} for a voxel in the center
# for shift in range(-5,6):
shift_from_center = -1
volume_axial_offset = optical_info['volume_shape'][0] // 2 + shift_from_center # for center
volume_type = '5ellipsoids'
# volume_type = 'ellipsoid'
# volume_type = 'shell'
# volume_type = 'single_voxel'

# Plot azimuth
# azimuth_plot_type = 'lines'
azimuth_plot_type = 'hsv'

# Create output directory
output_dir = f'reconstructions/recons_{volume_type}_{optical_info["volume_shape"][0]} \
                x{optical_info["volume_shape"][1]}x{optical_info["volume_shape"][2]}__{training_params["output_posfix"]}'
os.makedirs(output_dir, exist_ok=True)
torch.save({'optical_info' : optical_info,
            'training_params' : training_params,
            'volume_type' : volume_type}, f'{output_dir}/parameters.pt')

if volume_type == 'single_voxel':
    optical_info['n_micro_lenses'] = 1
    azimuth_plot_type = 'lines'



# Create a Birefringent Raytracer
rays = BirefringentRaytraceLFM(backend=backend, optical_info=optical_info)

# Compute the rays and use the Siddon algorithm to compute the intersections
#   with voxels.
# If a filepath is passed as argument, the object with all its calculations
#   get stored/loaded from a file.
startTime = time.time()
rays.compute_rays_geometry()
executionTime = (time.time() - startTime)
print('Ray-tracing time in seconds: ' + str(executionTime))

# Move ray tracer to GPU
if backend == BackEnds.PYTORCH:
    device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    # Force cpu, as for now cpu is faster
    device = "cpu"
    print(f'Using computing device: {device}')
    rays = rays.to(device)



# Create a volume
my_volume = BirefringentVolume.create_dummy_volume( backend=backend, optical_info=optical_info, \
                                                    vol_type=volume_type, \
                                                    volume_axial_offset=volume_axial_offset)

# Move volume to GPU if avaliable
my_volume = my_volume.to(device)
# Plot volume
with torch.no_grad():
    my_volume.plot_volume_plotly(optical_info, voxels_in=my_volume.get_delta_n().abs(), opacity=0.1)


with torch.no_grad():
    # Perform same calculation with torch
    startTime = time.time()
    ret_image_measured, azim_image_measured = rays.ray_trace_through_volume(my_volume)
    executionTime = (time.time() - startTime)
    print('Warmup time in seconds with Torch: ' + str(executionTime))

    # Store GT images
    Delta_n_GT = my_volume.get_delta_n().detach().clone()
    optic_axis_GT = my_volume.get_optic_axis().detach().clone()
    ret_image_measured = ret_image_measured.detach()
    azim_image_measured = azim_image_measured.detach()
    azim_comp_measured = torch.arctan2(torch.sin(azim_image_measured), \
                            torch.cos(azim_image_measured)).detach()


############# 
# Let's create an optimizer
# Initial guess
my_volume = BirefringentVolume( backend=backend, optical_info=optical_info, \
                                volume_creation_args = {'init_mode' : 'random'})
my_volume.members_to_learn.append('Delta_n')
my_volume.members_to_learn.append('optic_axis')
my_volume = my_volume.to(device)

optimizer = torch.optim.Adam(my_volume.get_trainable_variables(), lr=training_params['lr'])
loss_function = torch.nn.L1Loss()

# To test differentiability let's define a loss function L = |ret_image_torch|, and minimize it
losses = []
plt.ion()
figure = plt.figure(figsize=(18,6))
plt.rcParams['image.origin'] = 'lower'

co_gt, ca_gt = ret_image_measured*torch.cos(azim_image_measured), ret_image_measured*torch.sin(azim_image_measured)
for ep in tqdm(range(training_params['n_epochs']), "Minimizing"):
    optimizer.zero_grad()
    ret_image_current, azim_image_current = rays.ray_trace_through_volume(my_volume)
    # Vector difference
    # co_pred, ca_pred = ret_image_current*torch.cos(azim_image_current), ret_image_current*torch.sin(azim_image_current)
    # L = ((co_gt-co_pred)**2 + (ca_gt-ca_pred)**2).sqrt().mean()
    azim_diff = azim_comp_measured - torch.arctan2(torch.sin(azim_image_current), torch.cos(azim_image_current))
    L = loss_function(ret_image_measured, ret_image_current) + \
        training_params['azimuth_weight'] * (2 * (1 - torch.cos(azim_image_measured - azim_image_current))).mean()
    #     (torch.cos(azim_image_measured-azim_image_current)**2 + torch.sin(azim_image_measured-azim_image_current)**2).abs().mean()
        # cos + sine
        # 0.1*(torch.cos(azim_image_measured) - torch.cos(azim_image_current)).abs().mean() + 0.1*(torch.sin(azim_image_measured) - torch.sin(azim_image_current)).abs().mean()
        # (torch.atan2(torch.sin(azim_image_measured - azim_image_current), torch.cos(azim_image_measured - azim_image_current))).abs().mean()
        # (2 * (1 - torch.cos(azim_image_measured - azim_image_current))).mean()
        # loss_function(azim_image_measured, azim_image_current)

    # Calculate update of the my_volume (Compute gradients of the L with respect to my_volume)
    L.backward()
    # Apply gradient updates to the volume
    optimizer.step()
    # print(f'Ep:{ep} loss: {L.item()}')
    losses.append(L.item())


    if ep%10==0:
        plt.clf()
        plt.subplot(2,4,1)
        plt.imshow(ret_image_measured.detach().cpu().numpy())
        plt.colorbar()
        plt.title('Initial Retardance')
        plt.subplot(2,4,2)
        plt.imshow(azim_image_measured.detach().cpu().numpy())
        plt.colorbar()
        plt.title('Initial Azimuth')
        plt.subplot(2,4,3)
        plt.imshow(volume_2_projections(Delta_n_GT.unsqueeze(0))[0,0] \
                                        .detach().cpu().numpy())
        plt.colorbar()
        plt.title('Initial volume MIP')

        plt.subplot(2,4,5)
        plt.imshow(ret_image_current.detach().cpu().numpy())
        plt.colorbar()
        plt.title('Final Retardance')
        plt.subplot(2,4,6)
        plt.imshow(np.rad2deg(azim_image_current.detach().cpu().numpy()))
        plt.colorbar()
        plt.title('Final Azimuth')
        plt.subplot(2,4,7)
        plt.imshow(volume_2_projections(my_volume.get_delta_n().unsqueeze(0))[0,0] \
                                        .detach().cpu().numpy())
        plt.colorbar()
        plt.title('Final Volume MIP')
        plt.subplot(2,4,8)
        plt.plot(list(range(len(losses))),losses)
        plt.gca().yaxis.set_label_position("right")
        plt.gca().yaxis.tick_right()
        plt.xlabel('Epoch')
        plt.ylabel('Loss')

        figure.canvas.draw()
        figure.canvas.flush_events()
        time.sleep(0.1)
        plt.savefig(f"{output_dir}/Optimization_ep_{'{:02d}'.format(ep)}.pdf")
        time.sleep(0.1)


# Display
plt.savefig(f"{output_dir}/g_Optimization_final.pdf")
plt.show()
