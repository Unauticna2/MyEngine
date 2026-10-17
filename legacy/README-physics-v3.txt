MyEngine — ASM physics + Python objects and scenes
Windows x64 / MASM ml64 / OpenGL / CPython 3.11–3.13 x64

БЫСТРЫЙ ЗАПУСК
1. Распакуй архив в отдельную папку. Твои модели, текстуры и скрипты сохранены.
2. Запусти build.cmd: теперь нужно пересобрать EXE с Physics.asm и новыми
   экспортами. Старый EXE из предыдущей версии с новым Python API несовместим.
   В этом архиве нет устаревшего EXE, .obj сборки, .exp, .lib и __pycache__.
3. Используется твой python.ini. Если Python перемещён/конфигурации нет,
   запусти setup_python.cmd. Нужен обычный CPython x64 3.11, 3.12 или 3.13.
   Сторонних pip-пакетов и физической DLL не требуется.
4. AsmMapEngine.exe открывает map.json. Для физического демо:
   start_physics_demo.cmd
   или в командной строке:
   AsmMapEngine.exe map-physics.json

Для сборки нужны VS 2022 Community, инструменты C++ и Windows SDK.
build.cmd поддерживает установленную VS Community в стандартном каталоге.
Для другой установки используй x64 Native Tools Command Prompt.
Ошибки загрузки/скриптов записываются в engine.log рядом с EXE.

КАРТЫ И УПРАВЛЕНИЕ
map.json — твоя сцена: ландшафт и пол получили mesh-коллайдеры, добавлен
невидимый объект physics_controls со скриптом создания коробок.
map-before-physics.json — точная исходная map.json из загруженного MyEngine.zip.
map2.json, map-original.json, map-minimal.json, map-demo.json сохранены.
map-physics.json / map-physics2.json — две новые демонстрационные сцены.

Во всех сценах с physics_spawner.py:
  1 — создать и бросить коробку с Rigidbody и своим Python-скриптом.
  2 — удалить последнюю созданную коробку.
  3 — перезагрузить текущую сцену.
  4 — перейти в другую демонстрационную сцену.
  6 — открыть первую физическую демонстрацию.
В демо: WASD — ходить, Shift — быстрее, Space — прыгнуть.
ПКМ + мышь / стрелки — осмотр. Синий прямоугольник — портал между сценами.
В исходной карте сохранён свободный полёт: WASD, Space/Ctrl, Shift.
R — сброс камеры. Q/E — W-слои. Esc — выход.
Свет: F1/F2 — Y, F3/F4 — X, F6/F7 — Z. F5 — перечитать Python-скрипты.

ФИЗИКА НА АССЕМБЛЕРЕ
Physics.asm выполняет:
- интегрирование сил, гравитации, скоростей, вращения через кватернионы;
- OBB–OBB: коробки с произвольным поворотом, 15 разделяющих осей;
- OBB–triangle: коробки против треугольников меша;
- обход BVH полигонального ландшафта;
- импульсный решатель с массой, тензором инерции, трением и отскоком;
- коррекцию проникновений и определение опоры grounded.

Коробки могут быть динамическими, статическими и кинематическими.
Треугольные меши — статические или кинематические: подходят для ландшафта,
пола, стен и движущейся геометрии. Для движущегося физического объекта
с произвольной моделью используй box-коллайдер этой модели.

engine_physics.py хранит компоненты/настройки, строит BVH при загрузке,
подбирает пары коробок через пространственную сетку и передаёт события скриптам.
Проверки пересечений и физический отклик исполняются в Physics.asm.
Геометрия BVH локальная и общая для одинаковых мешей: изменение позиции,
поворота или масштаба экземпляра не требует перестройки дерева.

Окно работает в основном потоке, рендер, скрипты и нативная физика — в
отдельном update/render-потоке. Ресурсы читаются пулом до 4 потоков.
Связанные контакты решаются последовательно; Python-скрипты тоже.
Это собственный ECS-каркас с массивами компонентов, не Unity StaticEcs.

СОЗДАНИЕ ОБЪЕКТА ИЗ PYTHON
from engine_runtime import Behaviour

class Script(Behaviour):
    def update(self, dt):
        if self.world.input.pressed('1'):
            box = self.world.instantiate(
                'assets/Cube.obj',
                position=(0, 5, 0),
                rotation=(10, 30, 0),
                scale=(0.5, 0.5, 0.5),
                color=(1, 0.5, 0.1),
                texture='textures/checker.png',
                scripts=['scripts/physics_box.py'],
                collider={'type': 'box'},
                rigidbody={'mass': 2, 'friction': 0.6,
                           'restitution': 0.2, 'freeze_rotation': False})
            box.rigidbody.add_force((0, 3, -8), mode='impulse')

У instantiate есть необязательные name, w и layer_spacing. Если name
не указан, выдаётся уникальное имя. model=None создаёт пустой объект
для логики/триггера. Все пути относительно папки EXE. Возвращается Entity.
Позиции, повороты и масштабы сразу доступны, скрипт start вызывается
в безопасной точке кадра после создания. Затем идут update/fixed_update.
Можно назначить параметры экземпляру скрипта до его start:
  script = box.add_script('scripts/my_script.py')
  script.speed = 3
  script = box.get_script('my_script.py')

НАСТРОЙКИ И МЕТОДЫ ENTITY
entity.position = (x, y, z) / entity.position.x += 1
entity.rotation = (x, y, z) — градусы; порядок Rz * Ry * Rx.
entity.scale = (x, y, z) — ненулевой масштаб, применяется и к коллайдеру.
entity.color = (r, g, b) / entity.texture = 'textures/checker.png'
entity.move(x=0, y=0, z=0, w=0) / entity.rotate(x=0, y=0, z=0)
entity.w — положение вдоль W, entity.layer_spacing — шаг .4d.
entity.visible=False скрывает модель; коллайдер и логика остаются активными.
entity.active=False выключает модель, update, fixed_update и физику объекта.
entity.destroyed показывает, удалён ли объект.
entity.destroy() или world.destroy(entity) — удалить объект со скриптами.
world.find('имя') — Entity или None; world.find('player') — камера.

После destroy обычное обращение к трансформации вызывает ReferenceError:
старый объект не может изменить новую сущность, занявшую то же место в ECS.
Кэш мешей/текстур живёт до закрытия сцены, поэтому одинаковые объекты
можно создавать повторно без повторного чтения и загрузки модели на GPU.
Максимум 4096 одновременно зарегистрированных объектов; места переиспользуются.

КОМПОНЕНТЫ
box = entity.add_box_collider(size=(2,2,2), center=(0,0,0))
trigger = entity.add_box_trigger(size=(3,3,3))
mesh = entity.add_mesh_collider()
rb = entity.add_rigidbody(mass=1, use_gravity=True, friction=.6)
entity.remove_rigidbody()
entity.collider = None

Без size/center box-коллайдер берёт локальные габариты и центр модели.
Без модели размер по умолчанию (1,1,1), центр (0,0,0).
size задаёт полный размер в локальных единицах до применения scale.
Так, Cube.obj размером 2 и scale=.5 даёт коробку размером 1.
При смене W-слоя автоматические габариты .4d обновляются по его геометрии.
Позиция Entity — опорная точка модели; центр масс коробки следует center.

Настройки коллайдера в JSON / dictionary:
  {"type":"box", "size":[2,2,2], "center":[0,0,0],
   "isTrigger":false, "enabled":true, "friction":0.6,
   "restitution":0.0, "layer":0, "mask":4294967295}
  {"type":"mesh", "friction":0.8}
size/center можно задать объектом {"x":2,"y":2,"z":2}.
Для mesh size/center не используются: поверхность берётся из модели.
layer — 0..31; mask — битовая маска допустимых слоёв. Обе маски пары
должны разрешать столкновение. wSize, если указан, ограничивает бокс по W.
В Python доступны collider.isTrigger (также is_trigger), enabled, layer, mask.

RIGIDBODY
rb.mass — масса >0, минимум 0.0001.
rb.use_gravity / useGravity — учитывать гравитацию.
rb.gravity_scale — множитель гравитации, по умолчанию 1.
rb.is_kinematic / isKinematic — скрипт задаёт движение, силы его не меняют.
rb.freeze_rotation / freezeRotation — отключить физическое вращение.
rb.linear_damping, rb.angular_damping — сопротивление скорости, >=0.
rb.friction — коэффициент трения 0..10; rb.restitution — отскок 0..1.
rb.velocity = (x,y,z) — мировые единицы/секунду; доступны поля x/y/z.
rb.angular_velocity = (x,y,z) — радианы/секунду в мировых осях.
rb.grounded — есть опора с нормалью достаточно вверх.

rb.add_force((x,y,z)) — сила. Вызывай каждый fixed_update для постоянной силы.
rb.add_force((x,y,z), mode='impulse') — одноразовый импульс с учётом массы.
mode='acceleration' — ускорение; mode='velocity_change' — изменение скорости.
rb.add_torque((x,y,z)) — момент силы, вызывать в fixed_update.
rb.add_force_at_position(force, world_position) — сила и момент от её приложения.
rb.move_position((x,y,z)), rb.move_rotation((x,y,z)) — задать трансформацию,
особенно для кинематических платформ. Вызывать в fixed_update.
rb.teleport(position, rotation=None, reset_velocity=True) — телепортация.

Для динамических тел движение обычно задаётся скоростью/силами.
Прямое entity.position=... телепортирует тело; проверяется только итоговое
пересечение. Размер можно менять через entity.scale или collider.size.
При добавлении Rigidbody через instantiate без коллайдера автоматически
создаётся box. Отдельный add_rigidbody сам коллайдер не добавляет.
MeshCollider допускает Rigidbody только с is_kinematic=True.

СОБЫТИЯ СКРИПТА
from engine_runtime import Behaviour
class Script(Behaviour):
    def start(self): pass
    def update(self, dt): pass
    def fixed_update(self, dt): pass
    def on_collision_enter(self, collision): pass
    def on_collision_stay(self, collision): pass
    def on_collision_exit(self, collision): pass
    def on_trigger_enter(self, other): pass
    def on_trigger_stay(self, other): pass
    def on_trigger_exit(self, other): pass
    def on_destroy(self): pass

collision.other — другая Entity/камера.
collision.point, normal — тройки в мировых координатах.
normal направлена от другого объекта к этому.
collision.penetration — глубина; collision.impulse — нормальный импульс.
other.is_player отличает игрока. В exit другой объект может уже быть destroyed.
Триггер сообщает пересечение без физического отклика.
Для solid-событий нужен хотя бы один динамический Rigidbody.
Статические/кинематические пары могут давать trigger-события, но друг друга
не выталкивают. Mesh–mesh контактов нет, mesh проверяется против коробок.
События выдаются по фиксированным шагам, поэтому stay бывает чаще update.
В fixed_update и физических callbacks world.delta_time равен фиксированному
шагу; в update — шагу кадра. world.fixed_time — время физики.

Start вызывается после регистрации объектов; скрипты созданных в callback
объектов запускаются в следующей безопасной точке. Удаление откладывается
до завершения обхода. Исключение отключает один скрипт и пишется в engine.log.
F5 пересоздаёт экземпляры скриптов, вызывает on_destroy/start; переменные
старого экземпляра не сохраняются. Синтаксическая ошибка оставляет старый.
script.enabled=False отключает callbacks этого экземпляра.

СМЕНА СЦЕН
self.world.load_scene('map2.json')
self.world.reload_scene()
self.world.scene_path — путь текущей сцены.

Переход выполняется после текущего кадра. Сначала проверяется/загружается
новая сцена, затем закрывается старая и запускаются новые start.
Ошибка JSON, модели или загрузки скрипта оставляет прежнюю сцену и пишет
диагностику в engine.log. Ссылки на старые Entity после перехода недействительны.
При загрузке временно существуют ресурсы обеих сцен; для очень больших
карт учитывай этот пик памяти. Постоянные объекты между сценами пока не добавлены.

Старый формат map.json сохранён: model, positions, colors одинаковой длины.
Дополнительные массивы names, rotations, scales, textures, scripts, colliders
и новый rigidbodies тоже имеют по записи на объект; null означает отсутствие.
Пример:
  "colliders": [{"type":"mesh"}, {"type":"box"}],
  "rigidbodies": [null, {"mass":2,"friction":0.6,"restitution":0.1}]

Общая физика сцены:
  "physics": {"gravity":{"x":0,"y":-9.81,"z":0},
              "fixedDeltaTime":0.008333333333333333,
              "solverIterations":10,"maxSubsteps":8}
В Python: world.physics.gravity=(0,-9.81,0), fixed_delta_time,
solver_iterations (1..32), max_substeps (1..16), enabled.
Подшаги адаптируются к линейной скорости и толщине коробки.

ИГРОК
В демо камера получила вертикальный бокс и Rigidbody; управление в
scripts/physics_player.py. Нативный поворот мышью остаётся доступен.
world.camera.control_enabled=False отключает прежнее свободное перемещение.
world.camera.add_rigidbody(mass=80, friction=0) также отключает свободный полёт.
У камеры есть position, pitch, yaw, w, collider, rigidbody. Её физический бокс
всегда вертикален. В сцене camera.collider.center=(0,-.65,0) помещает камеру
выше центра тела. Ступеньки/приседание/автоподъём на уступы пока не реализованы.

4D, СВЕТ И ТЕКСТУРЫ
Физика работает в текущем трёхмерном срезе W: .4d выбирает OBJ-слой и его
коллайдер, вне диапазона объект не симулируется. Обычные OBJ присутствуют
при любом W, если не задан wSize. Гравитации и вращений XW/YW/ZW пока нет.
.4d содержит самостоятельные OBJ-блоки, разделённые отдельной строкой +.
Индексы каждого слоя начинаются заново. Шаг по умолчанию 0.1; Q/E меняют W.
Свет: world.light_rotation.x/y/z, углы в градусах.
PNG/BMP, UV из OBJ, смена entity.texture поддерживаются как раньше.
Дополнительные сведения о формате ресурсов: legacy/README-v2.txt;
разделы старого README про отсутствие физики/создания объектов уже устарели.

ОГРАНИЧЕНИЯ ЭТОЙ РЕАЛИЗАЦИИ
Это базовый импульсный решатель: один контакт на пару коробок, объединение
почти одинаковых нормалей соседних треугольников. Высокие стопки, очень тонкие
формы и большое отношение масс могут давать дрожание. Сложный меш можно
заменить упрощённым физическим мешем отдельного невидимого объекта.
Подшаги уменьшают пролёты сквозь поверхности, но полного swept CCD нет:
очень быстрые тела, резкая смена W и телепортации могут пропустить препятствие.
Нет joints, мягких тел, жидкости и динамического mesh–mesh решателя.
Вращение коробок, силы, трение и отскок есть; это не полная замена всех
подсистем физики Unity. Размер буфера — 1024 пересечения треугольников на
пару коробка–меш; при достижении лимита есть сообщение в engine.log.
Настройки физики/объекты изменяй в update/fixed_update/callbacks, не из
фоновых Python-потоков. Фоновая работа может передать результат в update.

ПРОВЕРКА
ASM-модули проверены MASM-совместимым JWasm в режиме Win64 без расширений.
Реальные машинные инструкции Physics.asm исполнялись с обвязкой Win64 ABI:
падение/опора, отскок, вращение, стопка коробок, силы, mesh-коллайдеры,
случайные OBB/OBB и OBB/triangle, создание/удаление объектов, порталы,
откат неудачной загрузки сцены и исходная пользовательская карта.
Проверен BVH загруженного terrain2.obj с поворотом и неравномерным масштабом.
Окно Windows и финальная линковка Microsoft link.exe здесь не запускались.
Собери EXE через build.cmd на своём Windows; это остаётся последней проверкой.
