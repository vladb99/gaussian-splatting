#
# Copyright (C) 2023, Inria
# GRAPHDECO research group, https://team.inria.fr/graphdeco
# All rights reserved.
#
# This software is free for non-commercial, research and evaluation use 
# under the terms of the LICENSE.md file.
#
# For inquiries contact  george.drettakis@inria.fr
#
import torch
from dreifus.camera import CameraCoordinateConvention, PoseType
from dreifus.matrix import Pose, Intrinsics
from dreifus.matrix.intrinsics_numpy import fov_to_focal_length
from gaussian_splatting.scene.cameras import Camera
import numpy as np
from gaussian_splatting.utils.general_utils import PILtoTorch
from gaussian_splatting.utils.graphics_utils import fov2focal

WARNED = False


def loadCam(args, id, cam_info, resolution_scale):
    orig_w, orig_h = cam_info.image.size

    if args.resolution in [1, 2, 4, 8]:
        resolution = round(orig_w / (resolution_scale * args.resolution)), round(orig_h / (resolution_scale * args.resolution))
    else:  # should be a type that converts to float
        if args.resolution == -1:
            if orig_w > 1600:
                global WARNED
                if not WARNED:
                    print("[ INFO ] Encountered quite large input images (>1.6K pixels width), rescaling to 1.6K.\n "
                          "If this is not desired, please explicitly specify '--resolution/-r' as 1")
                    WARNED = True
                global_down = orig_w / 1600
            else:
                global_down = 1
        else:
            global_down = orig_w / args.resolution

        scale = float(global_down) * float(resolution_scale)
        resolution = (int(orig_w / scale), int(orig_h / scale))

    resized_image_rgb = PILtoTorch(cam_info.image, resolution)

    gt_image = resized_image_rgb[:3, ...]
    loaded_mask = None

    if resized_image_rgb.shape[1] == 4:
        loaded_mask = resized_image_rgb[3:4, ...]

    return Camera(colmap_id=cam_info.uid, R=cam_info.R, T=cam_info.T,
                  FoVx=cam_info.FovX, FoVy=cam_info.FovY,
                  image=gt_image, gt_alpha_mask=loaded_mask,
                  image_name=cam_info.image_name, uid=id, data_device=args.data_device)


def cameraList_from_camInfos(cam_infos, resolution_scale, args):
    camera_list = []

    for id, c in enumerate(cam_infos):
        camera_list.append(loadCam(args, id, c, resolution_scale))

    return camera_list


def camera_to_JSON(id, camera: Camera):
    Rt = np.zeros((4, 4))
    Rt[:3, :3] = camera.R.transpose()
    Rt[:3, 3] = camera.T
    Rt[3, 3] = 1.0

    W2C = np.linalg.inv(Rt)
    pos = W2C[:3, 3]
    rot = W2C[:3, :3]
    serializable_array_2d = [x.tolist() for x in rot]
    camera_entry = {
        'id': id,
        'img_name': camera.image_name,
        'width': camera.width,
        'height': camera.height,
        'position': pos.tolist(),
        'rotation': serializable_array_2d,
        'fy': fov2focal(camera.FovY, camera.height),
        'fx': fov2focal(camera.FovX, camera.width),
        'cx': camera.cx,
        'cy': camera.cy
    }
    return camera_entry


# ==========================================================
# Conversion between Gaussian Splatting camera and dreifus Pose
# ==========================================================


def GS_camera_to_pose(camera: Camera) -> Pose:
    pose = Pose(camera.R.transpose(), camera.T, camera_coordinate_convention=CameraCoordinateConvention.OPEN_CV, pose_type=PoseType.WORLD_2_CAM)
    return pose


def GS_camera_to_intrinsics(camera: Camera) -> Intrinsics:
    fx = fov_to_focal_length(camera.FoVx, camera.image_width)
    fy = fov_to_focal_length(camera.FoVy, camera.image_height)
    cx = camera.cx
    cy = camera.cy
    intrinsics = Intrinsics(fx, fy, cx=cx, cy=cy)
    return intrinsics


def pose_to_GS_camera(pose: Pose, intrinsics: Intrinsics, img_w: int, img_h: int) -> Camera:
    fov_x = intrinsics.get_fovx(img_w)
    fov_y = intrinsics.get_fovy(img_h)
    cx = intrinsics.cx
    cy = intrinsics.cy
    dummy_img = torch.empty((3, img_h, img_w))

    pose = pose.change_pose_type(PoseType.CAM_2_WORLD, inplace=False)
    pose = pose.change_camera_coordinate_convention(CameraCoordinateConvention.OPEN_CV, inplace=False)
    pose = pose.change_pose_type(PoseType.WORLD_2_CAM, inplace=False)
    T = pose.get_translation()
    R = pose.get_rotation_matrix().transpose()

    camera = Camera(0, R, T, fov_x, fov_y, dummy_img, None, None, None, cx=cx, cy=cy)

    return camera