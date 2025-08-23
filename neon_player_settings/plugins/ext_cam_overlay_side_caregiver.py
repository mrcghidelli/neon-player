"""
(*)~---------------------------------------------------------------------------
Pupil - eye tracking platform
Copyright (C) Pupil Labs

Distributed under the terms of the GNU
Lesser General Public License (LGPL v3.0).
See COPYING and COPYING.LESSER for license details.
---------------------------------------------------------------------------~(*)
"""
import player_methods as pm

import weakref
import os
import json

from pyglui import ui
from observable import Observable
from plugin import Plugin
from pupil_recording import PupilRecording
from video_overlay.models.config import Configuration
from video_overlay.ui.management import UIManagement
from video_overlay.ui.menu import OverlayMenuRenderer, make_hflip_switch, make_vflip_switch
from video_overlay.utils.constraints import BooleanConstraint, ConstraintedValue
from video_overlay.workers.overlay_renderer import EyeOverlayRenderer

EXTERNAL_CAMERA_CONFIG = "side_caregiver"

class ExtCamera_Overlay_SideCaregiver(Observable, Plugin):
    icon_chr = chr(0xEC02)
    icon_font = "pupil_icons"

    order = 1.0

    def __init__(
        self,
        g_pool,
        scale=0.6,
        alpha=0.8,
        show_ellipses=True,
        ext_cam_config=None,
    ):
        super().__init__(g_pool)
        ext_cam_config = ext_cam_config or {"origin_x": 10, "origin_y": 60}

        self.current_frame_ts = None
        self.show_ellipses = ConstraintedValue(show_ellipses, BooleanConstraint())
        self._scale = scale
        self._alpha = alpha

        # Load MAC addresses from external_camera_mac_address.json
        json_file_path = os.path.join(os.path.dirname(__file__), "external_camera_mac_address.json")
        try:
            with open(json_file_path, 'r') as f:
                mac_data = json.load(f)
                self.mac_address = mac_data.get(EXTERNAL_CAMERA_CONFIG + "_mac_address", "b0-4a-6a-e9-80-57")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading MAC addresses: {e}")
            self.mac_address = "b0-4a-6a-e9-80-57"  # Default fallback

        self.ext_cam = self._setup_ext_cam(self.mac_address, ext_cam_config)

    def recent_events(self, events):
        if "frame" in events:
            frame = events["frame"]
            self.current_frame_ts = frame.timestamp
            self.ext_cam.draw_on_frame(frame)

    @property
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, val):
        self._scale = val
        self.ext_cam.config.scale.value = val

    @property
    def alpha(self):
        return self._alpha

    @alpha.setter
    def alpha(self, val):
        self._alpha = val
        self.ext_cam.config.alpha.value = val

    def init_ui(self):
        self.add_menu()
        self.menu.label = EXTERNAL_CAMERA_CONFIG.replace("_", " ") + " - External Camera Video Overlays"
        self.ui = UIManagementExternalCamera(self, self.menu, (self.ext_cam, ))

    def deinit_ui(self):
        self.ui.teardown()
        self.remove_menu()

    def _setup_ext_cam(self, mac_address, prefilled_config):
        video_path = self._video_path_for_ext_cam(mac_address)
        prefilled_config["video_path"] = video_path
        prefilled_config["scale"] = self.scale
        prefilled_config["alpha"] = self.alpha
        config = Configuration(**prefilled_config)
        overlay = EyeOverlayRenderer(config)
        return overlay

    def _video_path_for_ext_cam(self, mac_address: str) -> str:

        # Get all eye videos for mac_address
        recording = PupilRecording(self.g_pool.rec_dir)
        ext_cam_videos = list(recording.files().videos())

        ext_cam_video = next((v for v in ext_cam_videos if mac_address in str(v)), None)

        if ext_cam_video:
            print(ext_cam_video)
            return str(ext_cam_video)
        else:
            return f"/not/found/cam{mac_address}.mp4"

    def get_init_dict(self):
        return {
            "scale": self.scale,
            "alpha": self.alpha,
            "show_ellipses": self.show_ellipses.value,
            "ext_cam_config": self.ext_cam.config.as_dict(),
        }

    def make_current_pupil_datum_getter(self, eye_id):
        def _pupil_getter():
            try:
                pupil_data = self.g_pool.pupil_positions[eye_id, "2d"]
                if pupil_data:
                    closest_pupil_idx = pm.find_closest(
                        pupil_data.data_ts, self.current_frame_ts
                    )
                    current_datum_2d = pupil_data.data[closest_pupil_idx]
                else:
                    current_datum_2d = None

                pupil_data = self.g_pool.pupil_positions[eye_id, "3d"]

                if pupil_data:
                    closest_pupil_idx = pm.find_closest(
                        pupil_data.data_ts, self.current_frame_ts
                    )
                    current_datum_3d = pupil_data.data[closest_pupil_idx]
                else:
                    current_datum_3d = None
                return current_datum_2d, current_datum_3d
            except (IndexError, ValueError):
                return None

        return _pupil_getter
    

class UIManagementExternalCamera(UIManagement):
    def __init__(self, plugin, parent_menu, existing_overlays):
        self.plugin = weakref.ref(plugin)
        super().__init__(plugin, parent_menu, existing_overlays)

    def _add_menu_with_general_elements(self):
        self._parent_menu.append(
            ui.Info_Text(
                "Show the eye video overlaid on top of the world video. "
            )
        )
        self._parent_menu.append(
            ui.Slider(
                "alpha", self.plugin(), min=0.1, step=0.05, max=1.0, label="Opacity"
            )
        )
        self._parent_menu.append(
            ui.Slider(
                "scale", self.plugin(), min=0.2, step=0.05, max=1.0, label="Video Scale"
            )
        )

    def _add_overlay_menu(self, overlay):
        renderer = ExternalCameraOverlayMenuRenderer(overlay)
        self._menu_renderers[overlay] = renderer
        self._parent_menu.append(renderer.menu)

class ExternalCameraOverlayMenuRenderer(OverlayMenuRenderer):
    def _generic_overlay_elements(self):
        config = self.overlay().config
        return (make_hflip_switch(config), make_vflip_switch(config))

    def _not_valid_video_elements(self):
        video_path = self.overlay().config.video_path
        video_name = os.path.basename(video_path)
        return (ui.Info_Text(f"{video_name} was not recorded or cannot be found."),)