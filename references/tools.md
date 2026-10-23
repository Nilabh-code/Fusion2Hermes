# Fusion2Hermes command reference

All 93 commands exposed by the add-in, grouped by area, with their real
signatures read from `addon/server/command_handler.py` at the pinned commit.

Call them either as `mcp_fusion360_<name>` tools, or over the raw socket as
`{"type": "<name>", "params": {...}}` via `scripts/fm_client.py`.

Units are the document's; state mm explicitly (Fusion's default for new designs).
Every command acts on the **active document**. Most mutating commands return
structured deltas (`mass_g_delta`, `bbox_after`, ...) - use those to verify
instead of trusting the return code.

## Scene, measurement, inspection

- `get_scene_info`()
- `get_object_info`(name: str)
- `get_bounding_box`(name: str)
- `list_components`()
- `measure_distance`(entity_one: str, entity_two: str)
- `measure_angle`(entity_one: str, entity_two: str)
- `get_physical_properties`(body_name: str, accuracy: str = "medium")
- `create_section_analysis`(plane: str = "yz", offset: float = 0)
- `check_interference`(component_names: list, include_coincident_faces: bool = False)
- `compare_meshes`(mesh_name_a: str, mesh_name_b: str)

## Sketches

- `create_sketch`(plane: str = "xy", z_offset: float = None)
- `draw_rectangle`(width: float, height: float, origin_x: float = 0, origin_y: float = 0, origin_z: float = 0,)
- `draw_circle`(radius: float, center_x: float = 0, center_y: float = 0, center_z: float = 0,)
- `draw_line`(start_x: float, start_y: float, end_x: float, end_y: float, start_z: float = 0, end_z: float = 0,)
- `draw_arc`(center_x: float, center_y: float, start_x: float, start_y: float, sweep_angle: float, center_z: float = 0, start_z: float = 0,)
- `draw_spline`(spline_type: str, points: list, degree: int = 3)
- `create_polygon`(sides: int, radius: float, center_x: float = 0, center_y: float = 0, center_z: float = 0,)
- `add_constraint`(constraint_type: str, entity_one: int = None, entity_two: int = None, symmetry_line: int = None, sketch_name: str = None,)
- `auto_constrain`(sketch_name: str = None, result_option: int = 1,)
- `add_dimension`(dimension_type: str, value: float, entity_one: int = None, entity_two: int = None, sketch_name: str = None,)
- `offset_curve`(curve_index: int, offset_distance: float, direction_x: float = 1, direction_y: float = 0, sketch_name: str = None,)
- `trim_curve`(curve_index: int, point_x: float, point_y: float, sketch_name: str = None)
- `extend_curve`(curve_index: int, point_x: float, point_y: float, sketch_name: str = None)
- `project_geometry`(source_name: str, is_linked: bool = True, sketch_name: str = None)

## Solid features

- `extrude`(height: float, profile_index: int = 0, operation: str = "new_body", direction: str = "positive",)
- `revolve`(angle: float, profile_index: int = 0, axis_origin_x: float = 0, axis_origin_y: float = 0, axis_origin_z: float = 0, axis_direction_x: float = 1, axis_direction_y: float = 0, axis_direction_z: float = 0, operation: str = "new_body",)
- `sweep`(profile_index: int, path_sketch_name: str, path_curve_index: int = 0, operation: str = "new_body",)
- `loft`(profile_sketch_names: list, operation: str = "new_body")
- `fillet`(radius: float, body_name: str = None, body_index: int = 0, edge_selection: str = "all",)
- `chamfer`(distance: float, body_name: str = None, body_index: int = 0, edge_selection: str = "all",)
- `shell`(thickness: float, body_name: str = None, body_index: int = 0, face_selection: str = "top",)
- `mirror`(mirror_plane: str, body_name: str = None, body_index: int = 0)
- `create_hole`(diameter: float, depth: float, body_name: str = None, body_index: int = 0, face_selection: str = "top", center_x: float = 0, center_y: float = 0,)
- `rectangular_pattern`(body_name: str, x_count: int = 1, x_spacing: float = 1.0, y_count: int = 1, y_spacing: float = 1.0,)
- `circular_pattern`(body_name: str, count: int, axis: str = "z", total_angle: float = 360)
- `create_thread`(body_name: str, face_index: int, is_internal: bool = False, thread_type: str = "ISO Metric profile", thread_designation: str = "M10x1.5", thread_class: str = "6g", is_modeled: bool = False, is_full_length: bool = True, thread_length: float = None,)
- `draft_faces`(body_name: str, angle: float, face_selection: str = "vertical", pull_direction_plane: str = "xy", is_tangent_chain: bool = True,)
- `split_body`(body_name: str, splitting_plane: str = "xy", splitting_body: str = None, extend_tool: bool = True,)
- `split_face`(body_name: str, face_indices: list = None, splitting_plane: str = "xy", extend_tool: bool = True,)
- `offset_faces`(body_name: str, distance: float, face_selection: str = "top", face_indices: list = None,)
- `scale_body`(body_name: str, scale: float, scale_x: float = None, scale_y: float = None, scale_z: float = None, anchor_x: float = 0, anchor_y: float = 0, anchor_z: float = 0,)
- `move_body`(body_name: str, x: float = 0, y: float = 0, z: float = 0)
- `rename_body`(body_name: str, new_name: str)
- `suppress_feature`(feature_name: str)
- `unsuppress_feature`(feature_name: str)

## Primitives and booleans

- `create_box_parametric`(length, width, height, origin_x: float = 0.0, origin_y: float = 0.0, origin_z: float = 0.0, plane: str = "xy", component_name: str = None, body_name: str = None,)
- `create_box`(length: float, width: float, height: float, center_x: float = 0, center_y: float = 0, center_z: float = 0,)
- `create_cylinder`(radius: float, height: float, base_x: float = 0, base_y: float = 0, base_z: float = 0, axis: str = "z",)
- `create_sphere`(radius: float, center_x: float = 0, center_y: float = 0, center_z: float = 0,)
- `create_torus`(major_radius: float, minor_radius: float, center_x: float = 0, center_y: float = 0, center_z: float = 0, axis: str = "z",)
- `boolean_operation`(target_body: str, tool_body: str, operation: str = "join")

## Construction geometry

- `create_construction_plane`(method: str, plane: str = None, offset: float = None, angle: float = None, edge_name: str = None, plane_one: str = None, plane_two: str = None, point_one: list = None, point_two: list = None, point_three: list = None,)
- `create_construction_axis`(method: str, point_one: list = None, point_two: list = None, plane_one: str = None, plane_two: str = None, body_name: str = None, edge_index: int = None,)
- `create_ucs`(name: str = None, x: float = 0, y: float = 0, z: float = 0, angle_x: float = 0, angle_y: float = 0, angle_z: float = 0,)

## Assemblies

- `create_component`(name: str, parent_name: str = None)
- `add_joint`(component_one: str, component_two: str, joint_type: str = "rigid")
- `create_as_built_joint`(component_one: str, component_two: str, joint_type: str = "rigid")
- `create_rigid_group`(component_names: list, include_children: bool = True)

## Surfaces and sheet metal

- `patch_surface`(sketch_name: str, profile_index: int = 0, continuity: str = "connected")
- `stitch_surfaces`(body_names: list, tolerance: float = 0.01)
- `thicken_surface`(body_name: str, thickness: float, direction: str = "symmetric")
- `ruled_surface`(body_name: str, edge_index: int, distance: float = 1.0, rule_type: str = "normal",)
- `trim_surface`(body_name: str, tool_name: str)
- `create_flange`(body_name: str, edge_index: int, height: float = 1.0, angle: float = 90, bend_radius: float = None,)
- `create_bend`(body_name: str, bend_line_sketch: str = None, angle: float = 90, bend_radius: float = None,)
- `flat_pattern`(body_name: str)
- `unfold`(body_name: str, bend_indices: list = None)

## Parameters and design type

- `get_parameters`()
- `create_parameter`(name: str, value: float, unit: str, comment: str = None)
- `set_parameter`(name: str, value: float)
- `delete_parameter`(name: str)
- `get_design_type`()
- `set_design_type`(design_type: str)

## Appearance

- `set_appearance`(target_name: str, appearance_name: str, target_type: str = "body", face_index: int = None,)
- `set_color`(body_name: str, red: int, green: int, blue: int, opacity: float = 1.0,)

## Import / export

- `export_stl`(body_name: str, file_path: str = None)
- `export_step`(body_name: str, file_path: str = None)
- `export_f3d`(file_path: str = None)
- `export_view_sheet`(title: str = None, notes: str = "", views: list = None, image_size: list = None, output_dir: str = None,)
- `export`(format: str = None, body_name: str = None, file_path: str = None)
- `import_mesh`(file_path: str, component_name: str = None, units: str = "mm")

## Manufacturing / CAM

- `cam_list_setups`()
- `cam_list_operations`(setup_name: str)
- `cam_get_operation_info`(setup_name: str, operation_name: str)
- `cam_create_setup`(body_name: str, name: str = None, operation_type: str = "milling", stock_mode: str = "relative_box", stock_offset_sides: float = 0, stock_offset_top: float = 0, stock_offset_bottom: float = 0,)
- `cam_create_operation`(setup_name: str, strategy: str, name: str = None, tool_number: int = None, tool_diameter: float = None, stepdown: float = None, stepover: float = None, feed_rate: float = None, spindle_speed: float = None, coolant: str = "flood",)
- `cam_generate_toolpath`(setup_name: str = None, operation_name: str = None, generate_all: bool = False,)
- `cam_post_process`(setup_name: str, operation_name: str = None, post_processor: str = "fanuc", output_folder: str = None, output_units: str = "mm",)

## Session and escape hatch

- `ping`()
- `render_view`(view: str = "current", width: int = 1024, height: int = 768, fit: bool = True,)
- `delete_all`()
- `undo`()
- `execute_code`(code: str)
