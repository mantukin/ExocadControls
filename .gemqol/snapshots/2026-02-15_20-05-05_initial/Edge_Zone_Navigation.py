# <pep8 compliant>
bl_info = {
    "name": "Edge Zone Navigation (Roll & Pan) [3.3 Compat]",
    "author": "mantukin (IPD Workshop)",
    "version": (1, 20, 3), # Инкремент версии для исправления панорамирования
    "blender": (3, 3, 0), # Минимальная версия Blender
    "location": "View3D > Sidebar (N Panel) > View Tab > Edge Zones Panel, or View Menu",
    "description": "Adds interactive zones on edges of the 3D View. Right-Click+Drag in zones to roll (right) or pan (left/bottom). Cursor warps. Remembers state. (Adapted for Blender 3.3+, uses view_pan)",
    "warning": "Requires Blender 3.3+. Uses view_pan for panning.",
    "doc_url": "",
    "category": "3D View",
}
import bpy
import gpu
import math # Для радиан
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent

# --- Константы ---
DEFAULT_ROLL_ANGLE_DEGREES = math.radians(0.5) # Значение по умолчанию в радианах для свойства ANGLE
DEFAULT_PAN_SENSITIVITY = 20.0 # Пиксели на шаг панорамирования
DEFAULT_ZONE_THICKNESS = 25 # Для зон панорамирования
DEFAULT_ROLL_SENSITIVITY = 2.50

# --- Глобальные переменные ---
_global_op_instance = None
_draw_handler_ref = None
_shader = None

# --- Шейдер отрисовки ---
def get_shader():
    global _shader
    if _shader is None:
        try: _shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        except Exception:
            try: _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            except Exception as e_legacy: print(f"Failed to get shader: {e_legacy}"); return None
    return _shader

def create_rect_batch(rect_verts):
    shader = get_shader();
    if not shader or not rect_verts: return None
    indices = ((0, 1, 2), (0, 2, 3))
    positions = [tuple(rect_verts['tl']), tuple(rect_verts['tr']), tuple(rect_verts['br']), tuple(rect_verts['bl'])]
    for pos in positions:
        if not all(isinstance(coord, (int, float)) and math.isfinite(coord) for coord in pos):
            return None
    try: return batch_for_shader(shader, 'TRIS', {"pos": positions}, indices=indices)
    except Exception as e: print(f"Error creating batch: {e}"); return None

# --- Обработчик отрисовки ---
def draw_callback_px(op, context):
    try: _ = op.bl_idname; is_op_valid = True
    except (ReferenceError, AttributeError): is_op_valid = False
    if not is_op_valid: return

    region = context.region; view3d = context.space_data
    if not region or not view3d or view3d.type != 'VIEW_3D' or region.type != 'WINDOW': return

    try:
        prefs = op.get_prefs(context)
    except (ReferenceError, AttributeError): return

    is_dragging = getattr(op, "is_dragging", False)
    active_zone = getattr(op, "active_zone_type", 'NONE')

    try:
        roll_zone_coords = op.get_roll_zone_rect_coords(context, prefs) if prefs.enable_roll_zone else None
        pan_v_zone_coords = op.get_pan_v_zone_rect_coords(context, prefs) if prefs.enable_pan_vertical_zone else None
        pan_h_zone_coords = op.get_pan_h_zone_rect_coords(context, prefs) if prefs.enable_pan_horizontal_zone else None
    except (ReferenceError, AttributeError):
        return

    if not roll_zone_coords and not pan_v_zone_coords and not pan_h_zone_coords: return

    try:
        shader = get_shader()
        if not shader: return
        shader.bind(); gpu.state.blend_set('ALPHA')
        opacity = prefs.zone_opacity

        zones_to_draw = []
        if roll_zone_coords: zones_to_draw.append(('ROLL', roll_zone_coords))
        if pan_v_zone_coords: zones_to_draw.append(('PAN_V', pan_v_zone_coords))
        if pan_h_zone_coords: zones_to_draw.append(('PAN_H', pan_h_zone_coords))

        for zone_type, coords in zones_to_draw:
            is_active_zone = is_dragging and active_zone == zone_type
            base_color = prefs.zone_active_color if is_active_zone else prefs.zone_color
            final_color = (base_color[0], base_color[1], base_color[2], opacity)
            shader.uniform_float("color", final_color)
            batch_zone = create_rect_batch(coords)
            if batch_zone: batch_zone.draw(shader)

        gpu.state.blend_set('NONE')
    except ReferenceError:
        try: gpu.state.blend_set('NONE')
        except Exception: pass
    except Exception as e:
        print(f"Error during drawing: {e}")
        try: gpu.state.blend_set('NONE')
        except Exception: pass

# --- Остановка любого запущенного экземпляра / Очистка глобальных переменных ---
def cleanup_previous_state():
    """Очищает глобальные переменные и обработчики от предыдущего состояния."""
    global _global_op_instance, _draw_handler_ref

    if _draw_handler_ref is not None:
        try: bpy.types.SpaceView3D.draw_handler_remove(_draw_handler_ref, 'WINDOW')
        except (ValueError, RuntimeError) as e: pass
        _draw_handler_ref = None

    if _global_op_instance is not None:
        _global_op_instance = None

# --- Модальный оператор ---
class VIEW3D_OT_edge_zone_navigation(bpy.types.Operator):
    bl_idname = "view3d.edge_zone_navigation"; bl_label = "Run Edge Zone Navigation (Roll/Pan)"; bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    is_running: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    is_dragging: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    start_mouse_x: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    start_mouse_y: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    accumulated_dx: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})
    accumulated_dy: bpy.props.FloatProperty(default=0.0, options={'SKIP_SAVE'})
    last_mouse_region_x: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    last_mouse_region_y: bpy.props.IntProperty(default=0, options={'SKIP_SAVE'})
    cursor_was_hidden: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    active_zone_type: bpy.props.EnumProperty(
        items=[
            ('NONE', "None", "No zone active"),
            ('ROLL', "Roll", "Roll zone active (right edge)"),
            ('PAN_V', "Vertical Pan", "Vertical pan zone active (left edge)"),
            ('PAN_H', "Horizontal Pan", "Horizontal pan zone active (bottom edge)")
        ],
        name="Active Zone", default='NONE', options={'SKIP_SAVE'}
    )
    def get_prefs(self, context):
        try: return context.preferences.addons[__name__].preferences
        except KeyError:
            class DummyPrefs:
                enable_roll_zone = True; enable_pan_vertical_zone = True; enable_pan_horizontal_zone = True
                roll_zone_width = 365; pan_zone_thickness = 25
                zone_color = (0.2, 0.2, 0.8); zone_active_color = (0.8, 0.2, 0.2)
                zone_opacity = 0.15; hide_cursor_on_drag = True
                invert_roll_direction = True; invert_pan_vertical = False; invert_pan_horizontal = False
                roll_sensitivity = DEFAULT_ROLL_SENSITIVITY; roll_angle = DEFAULT_ROLL_ANGLE_DEGREES
                pan_sensitivity = DEFAULT_PAN_SENSITIVITY
                auto_start_listener = True
            print("Warning: Could not find addon preferences, using fallback defaults.")
            return DummyPrefs()

    # --- Расчет координат зон ---
    def get_roll_zone_rect_coords(self, context, prefs):
        region = context.region
        if not region: return None
        width = region.width; height = region.height; zone_width_px = prefs.roll_zone_width
        if width <= 0 or height <= 0 or zone_width_px <= 0: return None
        xmin = width - zone_width_px; xmax = width; ymin = 0; ymax = height
        if xmin < 0: xmin = 0; zone_width_px = width
        if xmin >= xmax or ymin >= ymax: return None
        return { 'tl': (xmin, ymax), 'tr': (xmax, ymax), 'br': (xmax, ymin), 'bl': (xmin, ymin),
                 'width': zone_width_px, 'height': height, 'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax }
    def get_pan_v_zone_rect_coords(self, context, prefs): # Левая зона
        region = context.region
        if not region: return None
        width = region.width; height = region.height; zone_thickness_px = prefs.pan_zone_thickness
        if width <= 0 or height <= 0 or zone_thickness_px <= 0: return None
        xmin = 0; xmax = zone_thickness_px; ymin = 0; ymax = height
        if xmax > width: xmax = width
        if xmin >= xmax or ymin >= ymax: return None
        return { 'tl': (xmin, ymax), 'tr': (xmax, ymax), 'br': (xmax, ymin), 'bl': (xmin, ymin),
                 'width': zone_thickness_px, 'height': height, 'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax }
    def get_pan_h_zone_rect_coords(self, context, prefs): # Нижняя зона
        region = context.region
        if not region: return None
        width = region.width; height = region.height; zone_thickness_px = prefs.pan_zone_thickness
        if width <= 0 or height <= 0 or zone_thickness_px <= 0: return None
        xmin = 0; xmax = width; ymin = 0; ymax = zone_thickness_px
        if prefs.enable_pan_vertical_zone: xmin = min(prefs.pan_zone_thickness, width)

        if ymax > height: ymax = height
        if xmin >= xmax or ymin >= ymax: return None
        return { 'tl': (xmin, ymax), 'tr': (xmax, ymax), 'br': (xmax, ymin), 'bl': (xmin, ymin),
                 'width': xmax - xmin, 'height': zone_thickness_px, 'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax }

    # --- Проверка зоны ---
    def get_active_zone(self, context, event, prefs):
        x, y = event.mouse_region_x, event.mouse_region_y

        if prefs.enable_roll_zone:
            coords = self.get_roll_zone_rect_coords(context, prefs)
            if coords and (coords['xmin'] <= x < coords['xmax'] and coords['ymin'] <= y < coords['ymax']):
                return 'ROLL'

        if prefs.enable_pan_vertical_zone:
            coords = self.get_pan_v_zone_rect_coords(context, prefs)
            if coords and (coords['xmin'] <= x < coords['xmax'] and coords['ymin'] <= y < coords['ymax']):
                return 'PAN_V'

        if prefs.enable_pan_horizontal_zone:
            coords = self.get_pan_h_zone_rect_coords(context, prefs)
            if coords and (coords['xmin'] <= x < coords['xmax'] and coords['ymin'] <= y < coords['ymax']):
                return 'PAN_H'

        return 'NONE'

    # --- Утилита ---
    def _restore_cursor(self, context):
        if self.cursor_was_hidden:
            try:
                if context.window: context.window.cursor_modal_restore()
                self.cursor_was_hidden = False
            except Exception as e: print(f"Error restoring cursor: {e}")

    # --- Модальный цикл ---
    def modal(self, context, event):
        global _global_op_instance
        if not self.is_running:
             self._restore_cursor(context); self.cancel_modal(context); return {'CANCELLED'}
        if not context.area or context.area.type != 'VIEW_3D':
             self._restore_cursor(context); self.cancel_modal(context); return {'CANCELLED'}

        prefs = self.get_prefs(context); area = context.area
        
        if prefs.auto_lock_to_cursor:
            view3d = context.space_data
            if view3d and view3d.type == 'VIEW_3D' and not view3d.lock_cursor:
                view3d.lock_cursor = True
        
        area.tag_redraw()

        # --- Обработка событий ---
        if event.type == 'RIGHTMOUSE':
            if event.value == 'PRESS':
                zone_hit = self.get_active_zone(context, event, prefs)
                if zone_hit != 'NONE':
                    self.is_dragging = True
                    self.active_zone_type = zone_hit
                    self.start_mouse_x = event.mouse_region_x
                    self.start_mouse_y = event.mouse_region_y
                    self.last_mouse_region_x = event.mouse_region_x
                    self.last_mouse_region_y = event.mouse_region_y
                    self.accumulated_dx = 0.0
                    self.accumulated_dy = 0.0
                    self.cursor_was_hidden = False
                    if prefs.hide_cursor_on_drag:
                        try:
                            if context.window: context.window.cursor_modal_set('NONE'); self.cursor_was_hidden = True
                        except Exception as e: print(f"Error hiding cursor: {e}")
                    return {'RUNNING_MODAL'}
                else:
                    self.is_dragging = False
                    self.active_zone_type = 'NONE'
                    return {'PASS_THROUGH'}

            elif event.value == 'RELEASE':
                if self.is_dragging:
                    self.is_dragging = False
                    self.accumulated_dx = 0.0
                    self.accumulated_dy = 0.0
                    self.active_zone_type = 'NONE'
                    self._restore_cursor(context)
                    area.tag_redraw()
                    return {'PASS_THROUGH'}
                else:
                    return {'PASS_THROUGH'}

        elif event.type == 'MOUSEMOVE':
            if self.is_dragging:
                delta_x = event.mouse_region_x - self.last_mouse_region_x
                delta_y = event.mouse_region_y - self.last_mouse_region_y

                warp_needed = False
                warp_x = context.region.x + self.start_mouse_x
                warp_y = context.region.y + self.start_mouse_y

                # --- Логика вращения (Правая зона) ---
                if self.active_zone_type == 'ROLL':
                    self.accumulated_dy += delta_y
                    sensitivity = prefs.roll_sensitivity
                    roll_angle_rad = prefs.roll_angle # ИСПРАВЛЕНИЕ: Значение уже в радианах
                    if sensitivity <= 0: sensitivity = 1.0

                    while abs(self.accumulated_dy) >= sensitivity:
                        base_direction = 1 if self.accumulated_dy > 0 else -1
                        if base_direction > 0 : self.accumulated_dy -= sensitivity
                        else: self.accumulated_dy += sensitivity
                        final_direction = -base_direction if prefs.invert_roll_direction else base_direction
                        try: bpy.ops.view3d.view_roll(angle=(final_direction * roll_angle_rad))
                        except Exception as e: print(f"Error executing view_roll: {e}"); self.accumulated_dy = 0; break
                    warp_needed = True
                    self.last_mouse_region_y = self.start_mouse_y

                # --- Логика вертикального панорамирования (Левая зона) ---
                elif self.active_zone_type == 'PAN_V':
                    self.accumulated_dy += delta_y
                    sensitivity = prefs.pan_sensitivity
                    if sensitivity <= 0: sensitivity = 1.0

                    while abs(self.accumulated_dy) >= sensitivity:
                        base_direction = 1 if self.accumulated_dy > 0 else -1
                        if base_direction > 0 : self.accumulated_dy -= sensitivity
                        else: self.accumulated_dy += sensitivity

                        pan_type = 'PANUP' if base_direction > 0 else 'PANDOWN'
                        if prefs.invert_pan_vertical:
                            pan_type = 'PANDOWN' if pan_type == 'PANUP' else 'PANUP'

                        # *** ИЗМЕНЕНИЕ: Используем view_pan как в space_view3d_3d_navigation.py ***
                        try:
                            bpy.ops.view3d.view_pan('INVOKE_REGION_WIN', type=pan_type)
                        except Exception as e:
                            print(f"Error executing view_pan ('INVOKE_REGION_WIN', {pan_type}): {e}")
                            self.accumulated_dy = 0 # Сброс при ошибке
                            break # Выход из цикла while
                    warp_needed = True
                    self.last_mouse_region_y = self.start_mouse_y

                # --- Логика горизонтального панорамирования (Нижняя зона) ---
                elif self.active_zone_type == 'PAN_H':
                    self.accumulated_dx += delta_x
                    sensitivity = prefs.pan_sensitivity
                    if sensitivity <= 0: sensitivity = 1.0

                    while abs(self.accumulated_dx) >= sensitivity:
                        base_direction = 1 if self.accumulated_dx > 0 else -1
                        if base_direction > 0 : self.accumulated_dx -= sensitivity
                        else: self.accumulated_dx += sensitivity

                        pan_type = 'PANRIGHT' if base_direction > 0 else 'PANLEFT'
                        if prefs.invert_pan_horizontal:
                            pan_type = 'PANLEFT' if pan_type == 'PANRIGHT' else 'PANRIGHT'

                        # *** ИЗМЕНЕНИЕ: Используем view_pan как в space_view3d_3d_navigation.py ***
                        try:
                             bpy.ops.view3d.view_pan('INVOKE_REGION_WIN', type=pan_type)
                        except Exception as e:
                            print(f"Error executing view_pan ('INVOKE_REGION_WIN', {pan_type}): {e}")
                            self.accumulated_dx = 0 # Сброс при ошибке
                            break # Выход из цикла while
                    warp_needed = True
                    self.last_mouse_region_x = self.start_mouse_x

                # --- Выполнение перемещения курсора ---
                if warp_needed and context.region and context.window:
                    current_screen_x = event.mouse_x
                    current_screen_y = event.mouse_y
                    if abs(current_screen_x - warp_x) > 2 or abs(current_screen_y - warp_y) > 2:
                        try:
                            context.window.cursor_warp(warp_x, warp_y)
                        except Exception as e: print(f"Error warping cursor: {e}")

                    if self.active_zone_type == 'ROLL' or self.active_zone_type == 'PAN_V':
                         self.last_mouse_region_y = self.start_mouse_y
                    if self.active_zone_type == 'PAN_H':
                         self.last_mouse_region_x = self.start_mouse_x

                if self.active_zone_type != 'PAN_H': self.last_mouse_region_x = event.mouse_region_x
                if self.active_zone_type != 'ROLL' and self.active_zone_type != 'PAN_V': self.last_mouse_region_y = event.mouse_region_y

                return {'RUNNING_MODAL'}
            else:
                return {'PASS_THROUGH'}

        elif event.type == 'TIMER':
            pass

        elif event.type in {'ESC'}:
            was_dragging = self.is_dragging
            if was_dragging:
                self._restore_cursor(context)
            self.cancel_modal(context)
            return {'CANCELLED'} if was_dragging else {'PASS_THROUGH'}

        return {'PASS_THROUGH'}

    # --- Жизненный цикл оператора ---
    def invoke(self, context, event):
        global _global_op_instance, _draw_handler_ref
        cleanup_previous_state()

        if context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Active space is not a 3D View"); return {'CANCELLED'}

        self.is_dragging = False
        self.accumulated_dx = 0.0; self.accumulated_dy = 0.0
        self.start_mouse_x = 0; self.start_mouse_y = 0
        self.last_mouse_region_x = 0; self.last_mouse_region_y = 0
        self.cursor_was_hidden = False
        self.active_zone_type = 'NONE'
        self.is_running = True
        _global_op_instance = self

        if _draw_handler_ref is None:
            try:
                args = (self, context)
                _draw_handler_ref = bpy.types.SpaceView3D.draw_handler_add(
                    draw_callback_px, args, 'WINDOW', 'POST_PIXEL'
                )
            except Exception as e:
                print(f"Error adding draw handler: {e}"); self.report({'ERROR'}, "Failed to add draw handler.")
                self.is_running = False; _global_op_instance = None; _draw_handler_ref = None
                return {'CANCELLED'}

        try:
            prefs = self.get_prefs(context)
            prefs.auto_start_listener = True
        except Exception as e:
            print(f"Warning: Could not set auto_start_listener on invoke: {e}")

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        print("Edge Zone Navigation: Started.")
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
    def cancel_modal(self, context):
        global _global_op_instance, _draw_handler_ref
        if self.is_running and _global_op_instance == self:
             self._restore_cursor(context)
             wm = context.window_manager
             if self._timer:
                 try: wm.event_timer_remove(self._timer)
                 except (ValueError, RuntimeError): pass
                 self._timer = None

             if _draw_handler_ref:
                 try: bpy.types.SpaceView3D.draw_handler_remove(_draw_handler_ref, 'WINDOW')
                 except (ValueError, RuntimeError): pass
                 _draw_handler_ref = None

             self.is_running = False
             _global_op_instance = None
             print("Edge Zone Navigation: Stopped.")
             if context.area:
                 try: context.area.tag_redraw()
                 except (ReferenceError, AttributeError): pass

        self.is_dragging = False
        self.accumulated_dx = 0.0; self.accumulated_dy = 0.0
        self.cursor_was_hidden = False
        self.active_zone_type = 'NONE'

# --- Настройки аддона ---
class EdgeZoneNavigationPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    # --- Общие ---
    zone_color: bpy.props.FloatVectorProperty( name="Zone Color (Idle)", description="Base color (RGB) when inactive", subtype='COLOR', size=3, min=0.0, max=1.0, default=(0.2, 0.2, 0.8) )
    zone_active_color: bpy.props.FloatVectorProperty( name="Zone Color (Active)", description="Base color (RGB) when RMB dragging in a zone", subtype='COLOR', size=3, min=0.0, max=1.0, default=(0.8, 0.2, 0.2) )
    zone_opacity: bpy.props.FloatProperty( name="Zone Opacity", description="Opacity (alpha) of the activation zones", default=0.15, min=0.0, max=1.0, subtype='FACTOR' )
    hide_cursor_on_drag: bpy.props.BoolProperty( name="Hide Cursor During Drag", description="Make the mouse cursor invisible while dragging in zones", default=True )
    auto_start_listener: bpy.props.BoolProperty( name="Start Automatically", description="Automatically start the zone listener when Blender starts or loads a file (requires saving preferences)", default=True )
    auto_lock_to_cursor: bpy.props.BoolProperty( name="Auto Lock View to 3D Cursor", description="Automatically enables 'Lock to 3D Cursor' for the view if it's not active", default=False )

    # --- Зона вращения (Правая) ---
    enable_roll_zone: bpy.props.BoolProperty( name="Enable Roll Zone (Right Edge)", description="Enable the view roll zone on the right edge", default=True )
    roll_zone_width: bpy.props.IntProperty( name="Roll Zone Width (px)", description="Width of the roll zone", default=400, min=5, max=600 )
    invert_roll_direction: bpy.props.BoolProperty( name="Invert Roll Direction", description="Reverse the direction of view roll when dragging", default=True )
    roll_sensitivity: bpy.props.FloatProperty( name="Roll Sensitivity (px/step)", description="Pixels of vertical drag per roll step. Lower is more sensitive.", default=2.5, min=1.0, soft_max=50.0, max=500.0 )
    roll_angle: bpy.props.FloatProperty( name="Roll Angle (°/step)", description="Degrees the view rolls per step", default=DEFAULT_ROLL_ANGLE_DEGREES, min=math.radians(0.1), soft_max=math.radians(10.0), max=math.radians(45.0), subtype='ANGLE', unit='ROTATION' )

    # --- Зоны панорамирования (Левая/Нижняя) ---
    enable_pan_vertical_zone: bpy.props.BoolProperty( name="Enable Pan Zone (Left Edge)", description="Enable the view pan zone on the left edge", default=True )
    enable_pan_horizontal_zone: bpy.props.BoolProperty( name="Enable Pan Zone (Bottom Edge)", description="Enable the view pan zone on the bottom edge", default=True )
    pan_zone_thickness: bpy.props.IntProperty( name="Pan Zone Thickness (px)", description="Thickness of the pan zones (width for left, height for bottom)", default=DEFAULT_ZONE_THICKNESS, min=5, max=600 )
    invert_pan_vertical: bpy.props.BoolProperty( name="Invert Vertical Pan", description="Reverse the up/down pan direction", default=False )
    invert_pan_horizontal: bpy.props.BoolProperty( name="Invert Horizontal Pan", description="Reverse the left/right pan direction", default=False )
    pan_sensitivity: bpy.props.FloatProperty( name="Pan Sensitivity (px/step)", description="Pixels of drag per pan step. Lower is more sensitive.", default=DEFAULT_PAN_SENSITIVITY, min=1.0, soft_max=50.0, max=500.0 )
    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        # --- Общие настройки ---
        box = col.box()
        box.label(text="General:")
        sub = box.column(align=True)
        sub.prop(self, "zone_color")
        sub.prop(self, "zone_active_color")
        sub.prop(self, "zone_opacity")
        sub.prop(self, "hide_cursor_on_drag")
        sub.prop(self, "auto_start_listener")
        sub.prop(self, "auto_lock_to_cursor")
        sub.separator() # Небольшой разделитель

        # --- Настройки зоны вращения ---
        box = col.box()
        # Помещаем переключатель внутрь бокса
        box.prop(self, "enable_roll_zone")
        # Используем sub-колонку, чтобы настройки были активны/неактивны вместе с чекбоксом
        sub = box.column(align=True)
        sub.active = self.enable_roll_zone # Делаем неактивным, если зона выключена
        sub.prop(self, "roll_zone_width")
        sub.prop(self, "roll_sensitivity")
        sub.prop(self, "roll_angle")
        sub.prop(self, "invert_roll_direction")
        sub.separator() # Небольшой разделитель

        # --- Настройки зон панорамирования ---
        box = col.box()
        # Помещаем оба переключателя внутрь бокса
        box.prop(self, "enable_pan_vertical_zone")
        box.prop(self, "enable_pan_horizontal_zone")

        # Используем sub-колонку для общих настроек панорамирования
        sub = box.column(align=True)
        # Делаем неактивным, если обе зоны выключены
        sub.active = self.enable_pan_vertical_zone or self.enable_pan_horizontal_zone
        sub.prop(self, "pan_zone_thickness")
        sub.prop(self, "pan_sensitivity")

        # Настройки инверсии делаем активными только если соответствующая зона включена
        sub_v = box.column(align=True)
        sub_v.active = self.enable_pan_vertical_zone
        sub_v.prop(self, "invert_pan_vertical")

        sub_h = box.column(align=True)
        sub_h.active = self.enable_pan_horizontal_zone
        sub_h.prop(self, "invert_pan_horizontal")

# --- Панель ---
class VIEW3D_PT_edge_zone_navigation_panel(bpy.types.Panel):
    bl_label = "Edge Zone Navigation"; bl_idname = "VIEW3D_PT_edge_zone_navigation_panel"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'View'

    def draw(self, context):
        layout = self.layout
        try: prefs = context.preferences.addons[__name__].preferences
        except KeyError: layout.label(text="Error: Prefs not found.", icon='ERROR'); return

        col = layout.column()
        global _global_op_instance
        op_idname = VIEW3D_OT_edge_zone_navigation.bl_idname
        stop_op_idname = "view3d.edge_zone_navigation_stop"
        is_running = _global_op_instance is not None

        if is_running:
             col.operator(stop_op_idname, text="Stop Edge Zones", icon='PLUGIN')
             col.label(text="Status: Running (RMB Drag Edges)")
        else:
             col.operator(op_idname, text="Start Edge Zones", icon='PLUGIN')
             col.label(text="Status: Stopped")

        col.label(text=f"Auto-Start: {'Enabled' if prefs.auto_start_listener else 'Disabled'}")
        col.separator()

        # --- Quick Settings Box (Переработанный) ---
        box = col.box()
        box.label(text="Quick Settings:")
        # Используем колонку с выравниванием для более плотного вертикального размещения
        q_col = box.column(align=True)

        # Секция включения зон
        q_col.label(text="Enable Zones:")
        q_col.prop(prefs, "enable_roll_zone", text="Roll (Right)")
        q_col.prop(prefs, "enable_pan_vertical_zone", text="Vert Pan (Left)")
        q_col.prop(prefs, "enable_pan_horizontal_zone", text="Horiz Pan (Bottom)")
        q_col.separator(factor=0.5) # Меньший разделитель

        # Секция размеров и прозрачности
        q_col.label(text="Sizing & Opacity:")
        q_col.prop(prefs, "roll_zone_width", text="Roll Width")
        q_col.prop(prefs, "pan_zone_thickness", text="Pan Thickness")
        q_col.prop(prefs, "zone_opacity", text="Opacity")
        q_col.separator(factor=0.5)

        # Секция чувствительности и угла
        q_col.label(text="Sensitivity & Angle:")
        q_col.prop(prefs, "roll_sensitivity", text="Roll Sens.")
        q_col.prop(prefs, "pan_sensitivity", text="Pan Sens.")
        q_col.prop(prefs, "roll_angle", text="Roll Angle")
        q_col.separator(factor=0.5)

        # Секция инверсии и скрытия курсора
        q_col.label(text="Invert & Hide:")
        q_col.prop(prefs, "invert_roll_direction", text="Invert Roll")
        q_col.prop(prefs, "invert_pan_vertical", text="Invert Vert Pan")
        q_col.prop(prefs, "invert_pan_horizontal", text="Invert Horiz Pan")
        q_col.prop(prefs, "hide_cursor_on_drag", text="Hide Cursor")
        q_col.separator(factor=0.5)

        # Секция вида
        q_col.label(text="View:")
        q_col.prop(prefs, "auto_lock_to_cursor", text="Auto Lock to Cursor")

        # Ссылка на полные настройки остается ниже бокса
        col.separator() # Отступ перед кнопкой "More Settings"
        op = col.operator("preferences.addon_show", text="More Settings..."); op.module = __name__

# --- Оператор остановки ---
class VIEW3D_OT_edge_zone_navigation_stop(bpy.types.Operator):
    bl_idname = "view3d.edge_zone_navigation_stop"; bl_label = "Stop Edge Zone Navigation"; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        global _global_op_instance
        return _global_op_instance is not None

    def execute(self, context):
        global _global_op_instance
        op_to_cancel = _global_op_instance
        if op_to_cancel:
            try:
                prefs = context.preferences.addons[__name__].preferences
                prefs.auto_start_listener = False
            except KeyError: pass
            except Exception as e: print(f"Error accessing prefs on stop: {e}")
            try: op_to_cancel.cancel_modal(context)
            except Exception as e:
                print(f"Error calling cancel_modal on {op_to_cancel}: {e}")
                cleanup_previous_state()
        else:
            self.report({'WARNING'}, "Edge Zone Navigation was not running or reference lost.")
            cleanup_previous_state()
        _global_op_instance = None
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    try: area.tag_redraw()
                    except Exception: pass
        return {'FINISHED'}

# --- Регистрация меню ---
def menu_func_start(self, context):
    op_idname = VIEW3D_OT_edge_zone_navigation.bl_idname
    global _global_op_instance; is_running = _global_op_instance is not None
    if not is_running: self.layout.operator(op_idname, text="Start Edge Zone Navigation")
def menu_func_stop(self, context):
    stop_op_idname = VIEW3D_OT_edge_zone_navigation_stop.bl_idname
    global _global_op_instance; is_running = _global_op_instance is not None
    if is_running: self.layout.operator(stop_op_idname, text="Stop Edge Zone Navigation")

# --- Обработчик загрузки ---
@persistent
def load_post_handler(dummy):
    cleanup_previous_state()
    # The persistent timer will handle restarts. We just need to ensure it's registered.
    if not bpy.app.timers.is_registered(auto_start_handler):
        # Use a small delay to allow UI to build after file load
        bpy.app.timers.register(auto_start_handler, first_interval=0.5)
def auto_start_handler():
    """Timer function to ensure the operator is running if auto-start is enabled."""
    global _global_op_instance

    try:
        # Context can be incomplete during startup or screen changes
        if not bpy.context.window or not bpy.context.screen:
            return 1.0 # Try again in 1 sec

        prefs = bpy.context.preferences.addons[__name__].preferences
        is_running = _global_op_instance is not None

        if prefs.auto_start_listener and not is_running:
            context_override_dict = None
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    # Find a window region within the 3D view area
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            context_override_dict = {
                                "window": bpy.context.window,
                                "screen": bpy.context.screen,
                                "area": area,
                                "region": region,
                                "space_data": area.spaces.active
                            }
                            break
                    if context_override_dict:
                        break
            
            if context_override_dict:
                try:
                    # Use temp_override for a more robust context-safe operator call,
                    # which is better for timers running in the background.
                    with bpy.context.temp_override(**context_override_dict):
                        bpy.ops.view3d.edge_zone_navigation('INVOKE_DEFAULT')
                except RuntimeError:
                    # This can happen if the context is not quite right (e.g., during a workspace switch)
                    # or if the operator is already running. The timer will simply try again.
                    pass
                except Exception as e:
                    print(f"Edge Zone Navigation: Auto-start timer error: {e}")

    except (AttributeError, KeyError):
        # This can happen if prefs are not ready on startup. The timer will retry.
        pass

    return 1.0 # Reschedule to run again in 1 second.

# --- Регистрация/Отмена регистрации ---
classes = (
    EdgeZoneNavigationPreferences,
    VIEW3D_OT_edge_zone_navigation,
    VIEW3D_OT_edge_zone_navigation_stop,
    VIEW3D_PT_edge_zone_navigation_panel,
)
def register():
    global _shader, _draw_handler_ref
    _shader = None; _draw_handler_ref = None

    for cls in classes:
        try: bpy.utils.register_class(cls)
        except ValueError: pass

    try:
        bpy.types.VIEW3D_MT_view.append(menu_func_start)
        bpy.types.VIEW3D_MT_view.append(menu_func_stop)
    except Exception as e: print(f"Error adding menu items: {e}")

    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)

    if not bpy.app.timers.is_registered(auto_start_handler):
        bpy.app.timers.register(auto_start_handler, first_interval=0.5)
def unregister():
    global _shader, _global_op_instance, _draw_handler_ref
    cleanup_previous_state()

    if bpy.app.timers.is_registered(auto_start_handler):
        bpy.app.timers.unregister(auto_start_handler)

    if load_post_handler in bpy.app.handlers.load_post:
        try: bpy.app.handlers.load_post.remove(load_post_handler)
        except Exception as e: print(f"Error removing load_post handler: {e}")

    try: bpy.types.VIEW3D_MT_view.remove(menu_func_start)
    except Exception as e: pass # Игнорировать, если не найдено
    try: bpy.types.VIEW3D_MT_view.remove(menu_func_stop)
    except Exception as e: pass # Игнорировать, если не найдено

    for cls in reversed(classes):
        try: bpy.utils.unregister_class(cls)
        except RuntimeError as e: print(f"Warning: Could not unregister class '{cls.__name__}': {e}")

    _shader = None; _global_op_instance = None; _draw_handler_ref = None

if __name__ == "__main__":
    print("--- Running Addon Registration Test ---")
    try: print("Attempting Unregister..."); unregister(); print("Unregister complete.")
    except Exception as e: print(f"ERROR during test unregister: {e}"); import traceback; traceback.print_exc()
    try: print("Attempting Register..."); register(); print("Register complete.")
    except Exception as e: print(f"ERROR during test register: {e}"); import traceback; traceback.print_exc()
    print("--- Addon Registration Test Finished ---")
