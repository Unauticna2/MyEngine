from engine_runtime import Behaviour
class Script(Behaviour):
    def __init__(self):self.last_state=None
    def start(self):
        self.world.log('R27: N spawn, F8 save PNG, F9 restore; 1 toggle Point, 2 negative Point, 3 aim Spot, 4 water wave.')
    def update(self,dt):
        keys=self.world.input;point=self.world.find('Point Light');spot=self.world.find('Spot Light')
        if keys.pressed('1'):point.light['enabled']=not point.light['enabled']
        if keys.pressed('2'):point.light['intensity']=-point.light['intensity']
        if keys.down('3'):spot.rotate(y=45*dt)
        if keys.pressed('4'):self.world.find('Water').liquid.splash(strength=1)
        state=self.world.saves.state('demo')
        if state!=self.last_state:
            self.last_state=state
            self.world.log('PNG:',state,self.world.saves.error('demo'))
