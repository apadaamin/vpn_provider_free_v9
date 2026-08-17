import asyncio
class WorkQueue:
    def __init__(self,workers=4): self.q=asyncio.Queue(); self.workers=workers; self.tasks=[]
    async def put(self,fn,*args,**kwargs): await self.q.put((fn,args,kwargs))
    async def worker(self):
        while True:
            fn,args,kwargs=await self.q.get()
            try: await fn(*args,**kwargs)
            finally: self.q.task_done()
    async def start(self): self.tasks=[asyncio.create_task(self.worker()) for _ in range(self.workers)]
    async def join(self): await self.q.join()
    async def stop(self):
        for t in self.tasks:t.cancel()
