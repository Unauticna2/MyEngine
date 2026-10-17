#include <stdint.h>
#define MS __attribute__((ms_abi))
extern void MS PhysicsPrepare(void*,uint32_t);
extern void MS PhysicsIntegrate(void*,uint32_t,void*);
extern int MS PhysicsBoxBox(void*,void*,void*);
extern int MS PhysicsBoxTriangle(void*,void*,void*,void*);
extern uint32_t MS PhysicsBoxContacts(void*,uint32_t,void*,uint32_t);
extern uint32_t MS PhysicsMeshContacts(void*,void*,void*,uint32_t);
extern void MS PhysicsSolve(void*,uint32_t,uint32_t);
void BridgePhysicsPrepare(void*a,uint32_t b){PhysicsPrepare(a,b);}
void BridgePhysicsIntegrate(void*a,uint32_t b,void*c){PhysicsIntegrate(a,b,c);}
int BridgePhysicsBoxBox(void*a,void*b,void*c){return PhysicsBoxBox(a,b,c);}
int BridgePhysicsBoxTriangle(void*a,void*b,void*c,void*d){return PhysicsBoxTriangle(a,b,c,d);}
uint32_t BridgePhysicsBoxContacts(void*a,uint32_t b,void*c,uint32_t d){return PhysicsBoxContacts(a,b,c,d);}
uint32_t BridgePhysicsMeshContacts(void*a,void*b,void*c,uint32_t d){return PhysicsMeshContacts(a,b,c,d);}
void BridgePhysicsSolve(void*a,uint32_t b,uint32_t c){PhysicsSolve(a,b,c);}
