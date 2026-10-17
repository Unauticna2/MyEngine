"""Developer nodes: the editor calls register(api) when opening Blueprints.

The generators return Python source, not values to calculate in the editor.
Use context.input for a linked port/default; context.literal quotes a parameter.
"""
def register(api):
    api.define(
        'Project.Time', title='Game time', hint='Seconds since Play started.',
        outputs={'value': 'number'}, expression=lambda c: 'self.world.time')
    api.define(
        'Project.Sine', title='Sine', hint='Sine of an angle in radians.',
        params={'angle': 0}, inputs={'angle': 'number'}, outputs={'value': 'number'},
        expression=lambda c: "__import__('math').sin(" + c.input('angle') + ')')
    api.define(
        'Project.DataNumber', title='Data asset number',
        hint='Reads a numeric field from a shared Scriptable Object.',
        params={'path': 'assets/data/Mover.scriptable.json', 'field': 'speed'},
        outputs={'value': 'number'},
        expression=lambda c: 'float(self.world.resources.scriptable(' + c.literal('path') + ')[' + c.literal('field') + '])')
    api.define(
        'Project.LogNumber', title='Log number', hint='Write a number to the Console.',
        params={'value': 0}, inputs={'in': 'exec', 'value': 'number'}, outputs={'next': 'exec'},
        action=lambda c: 'self.world.log(' + c.input('value') + ')')
