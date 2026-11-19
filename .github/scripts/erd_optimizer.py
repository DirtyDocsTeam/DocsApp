"""Deterministic, bounded optimization and obstacle-aware ERD routing (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
import logging
import math
import random

Point = tuple[float, float]
TRANSPORT_GAP = 96
MERGE_CLEARANCE = 18


@dataclass(frozen=True)
class LayoutOptions:
    steps: int = 800
    routing_passes: int = 2
    seed: int = 0

    def __post_init__(self):
        if type(self.steps) is not int or not 0 <= self.steps <= 100_000:
            raise ValueError('optimization.steps must be an integer in 0..100000')
        if type(self.routing_passes) is not int or not 0 <= self.routing_passes <= 10:
            raise ValueError('optimization.routing_passes must be an integer in 0..10')
        if type(self.seed) is not int:
            raise ValueError('optimization.seed must be an integer')


def crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    def side(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    return side(a,b,c)*side(a,b,d) < 0 and side(c,d,a)*side(c,d,b) < 0


def hits_rect(a: Point, b: Point, rect, clearance: float = 0) -> bool:
    """Liang–Barsky clipping, including contained and boundary-touching segments."""
    left, top = rect.x-clearance, rect.y-clearance
    right, bottom = rect.x+rect.width+clearance, rect.y+rect.height+clearance
    if max(a[0],b[0]) < left or min(a[0],b[0]) > right or max(a[1],b[1]) < top or min(a[1],b[1]) > bottom:
        return False
    lo, hi = 0., 1.
    dx, dy = b[0]-a[0], b[1]-a[1]
    for p,q in ((-dx,a[0]-left),(dx,right-a[0]),(-dy,a[1]-top),(dy,bottom-a[1])):
        if p == 0:
            if q < 0:
                return False
        elif p < 0:
            lo = max(lo,q/p)
        else:
            hi = min(hi,q/p)
        if lo > hi:
            return False
    return True


def optimize_grid(positioned, relations, options: LayoutOptions, fixed, row_height=26, header=34):
    """Anneal swaps of safe grid cells using a cheap geometric surrogate, keeping the best.

    Exact obstacle routing runs AFTER placement; running A* for every proposed swap would
    make --check unreasonably expensive. The surrogate includes card hits, crossings and
    connection length. A fixed proposal count, not a time limit, makes artifacts reproducible.
    """
    if not options.steps or len(positioned) < 2:
        return positioned
    by_name = {item.table.name: i for i,item in enumerate(positioned)}
    edges = []
    neighbours = [set() for _ in positioned]
    for rel in relations:
        c,p = by_name[rel.child],by_name[rel.parent]
        cr = next(i for i,col in enumerate(positioned[c].table.columns) if col.name == rel.column)
        pr = next(i for i,col in enumerate(positioned[p].table.columns) if col.name == rel.parent_column)
        edges.append((c,p,header+(cr+.5)*row_height,header+(pr+.5)*row_height))
        neighbours[c].add(p)
        neighbours[p].add(c)
    mutable = [i for i,item in enumerate(positioned) if item.table.name not in fixed]
    if len(mutable) < 2:
        return positioned

    def fitness(items):
        segments=[]
        length=0.
        for c,p,cy,py in edges:
            a,b=items[c].rect,items[p].rect
            facing = a.center[0] < b.center[0]
            start=(a.x+(a.width if facing else 0),a.y+cy)
            end=(b.x+(0 if facing else b.width),b.y+py)
            segments.append((c,p,start,end))
            length += abs(start[0]-end[0])+abs(start[1]-end[1])
        blocked=sum(hits_rect(a,b,item.rect) for c,p,a,b in segments
                    for i,item in enumerate(items) if i != c and i != p)
        intersections=sum(crosses(a,b,c,d) for i,(u,v,a,b) in enumerate(segments)
                          for x,y,c,d in segments[i+1:] if not ({u,v}&{x,y}))
        return blocked*12 + intersections*2 + length/2000

    rng=random.Random(options.seed)
    current=list(positioned)
    current_score=best_score=fitness(current)
    best=list(current)
    for step in range(options.steps):
        first=rng.choice(mutable)
        if neighbours[first] and rng.random() < .65:
            x=sum(current[i].rect.center[0] for i in neighbours[first])/len(neighbours[first])
            y=sum(current[i].rect.center[1] for i in neighbours[first])/len(neighbours[first])
            nearby=sorted((i for i in mutable if i != first),
                          key=lambda i:(abs(current[i].rect.center[0]-x)+abs(current[i].rect.center[1]-y),i))
            second=rng.choice(nearby[:6])
        else:
            second=rng.choice(mutable)
        if first == second:
            continue
        a,b=current[first],current[second]
        trial=list(current)
        trial[first]=replace(a,rect=replace(a.rect,x=b.rect.x,y=b.rect.y))
        trial[second]=replace(b,rect=replace(b.rect,x=a.rect.x,y=a.rect.y))
        # Fixed anchors may not be on the grid; preserve their clearance too.
        if fixed and any(math.hypot(max(i.rect.x-(j.rect.x+j.rect.width),j.rect.x-(i.rect.x+i.rect.width),0),
                                   max(i.rect.y-(j.rect.y+j.rect.height),j.rect.y-(i.rect.y+i.rect.height),0)) < 48
                         for k,i in enumerate(trial) if k in (first,second)
                         for n,j in enumerate(trial) if n != k):
            continue
        score=fitness(trial)
        temperature=40*(1-step/max(1,options.steps))**2+.25
        if score <= current_score or rng.random() < math.exp(min(0,(current_score-score)/temperature)):
            current,current_score=trial,score
        if score < best_score:
            best,best_score=list(trial),score
    return best


def compact(points):
    result=[]
    for point in points:
        if result and result[-1] == point:
            continue
        while len(result)>1 and ((result[-2][0] == result[-1][0] == point[0]) or
                                 (result[-2][1] == result[-1][1] == point[1])):
            result.pop()
        result.append(point)
    return tuple(result)


def overlap_length(first, second):
    """Length shared by collinear segments, including links with a common table."""
    total = 0.
    for a, b in zip(first, first[1:]):
        for c, d in zip(second, second[1:]):
            for axis in (0, 1):
                other = 1-axis
                if a[other] == b[other] == c[other] == d[other]:
                    total += max(0, min(max(a[axis],b[axis]),max(c[axis],d[axis])) -
                                 max(min(a[axis],b[axis]),min(c[axis],d[axis])))
    return total


def trim_ports(points, distance=12):
    """Exclude only the short common terminal stubs, never the rest of a shared link."""
    points = list(points)
    for reverse in (False, True):
        if reverse:
            points.reverse()
        left = distance
        while len(points)>1 and left:
            a,b=points[:2]
            length=abs(a[0]-b[0])+abs(a[1]-b[1])
            if length <= left:
                points.pop(0)
                left -= length
            else:
                points[0]=(a[0]+(b[0]-a[0])*left/length,a[1]+(b[1]-a[1])*left/length)
                left=0
    points.reverse()
    return tuple(points)


def port_aprons(positioned):
    """Reserve side corridors for terminal fans, adapting to narrow card gaps."""
    aprons=[]
    for item in positioned:
        r=item.rect
        for side in (-1,1):
            gaps=[r.x-(other.rect.x+other.rect.width) if side<0 else other.rect.x-(r.x+r.width)
                  for other in positioned if other is not item and
                  other.rect.y < r.y+r.height+24 and other.rect.y+other.rect.height > r.y-24 and
                  (other.rect.x+other.rect.width <= r.x if side<0 else other.rect.x >= r.x+r.width)]
            depth=min(160,max(12,(min(gaps)-TRANSPORT_GAP)/2)) if gaps else 160
            edge=r.x if side<0 else r.x+r.width
            aprons.append((item.table.name,replace(r,x=edge-depth if side<0 else edge,y=r.y-12,
                                                  width=depth,height=r.height+24)))
    return aprons


def endpoint_rows(positioned, rel):
    items={item.table.name:item for item in positioned}
    rows={}
    for name,column in ((rel.child,rel.column),(rel.parent,rel.parent_column)):
        item=items[name]
        index=next(i for i,c in enumerate(item.table.columns) if c.name==column)
        rows.setdefault(name,set()).add(item.rect.y+34+(index+.5)*26)
    return rows


def apron_allows(a,b,hits,rows):
    return all(a[1]==b[1] and a[1] in rows.get(name,()) for name in hits)


def endpoint_keys(rel):
    return {(name,column,side) for name,column in ((rel.child,rel.column),(rel.parent,rel.parent_column))
            for side in (-1,1)}


def merge_junctions(positioned, paths):
    """Find every branch of a shared tree, including intermediate trunk junctions."""
    groups={}
    items={item.table.name:item for item in positioned}
    for rel,(points,cs,ps) in paths.items():
        for key,outward in (((rel.child,rel.column,cs),points),
                            ((rel.parent,rel.parent_column,ps),tuple(reversed(points)))):
            groups.setdefault(key,[]).append(outward)
    zones=[]
    for key,routes in sorted(groups.items()):
        if len(routes)<2:
            continue
        for x,y in sorted({point for route in routes for point in route[1:-1]}):
            counts={}
            radius=0.
            for route in routes:
                rays=set()
                for a,b in zip(route,route[1:]):
                    if a[1]==b[1]==y and min(a[0],b[0])<=x<=max(a[0],b[0]):
                        if min(a[0],b[0])<x:rays.add((-1,0))
                        if max(a[0],b[0])>x:rays.add((1,0))
                    elif a[0]==b[0]==x and min(a[1],b[1])<=y<=max(a[1],b[1]):
                        if min(a[1],b[1])<y:rays.add((0,-1))
                        if max(a[1],b[1])>y:rays.add((0,1))
                for ray in rays:counts[ray]=counts.get(ray,0)+1
                for index,p in enumerate(route[1:-1],1):
                    if p==(x,y):
                        a,b=route[index-1],route[index+1]
                        radius=max(radius,min(12,(abs(a[0]-x)+abs(a[1]-y))*.45,
                                                (abs(b[0]-x)+abs(b[1]-y))*.45))
            shared=[ray for ray,count in counts.items() if count>1]
            if len(counts)<3 or not shared:
                continue
            contacts=[(x,y),*((x+dx*radius,y+dy*radius) for dx,dy in shared)]
            left,right=min(p[0] for p in contacts),max(p[0] for p in contacts)
            top,bottom=min(p[1] for p in contacts),max(p[1] for p in contacts)
            template=items[key[0]].rect
            zones.append((key,replace(template,x=left-MERGE_CLEARANCE,y=top-MERGE_CLEARANCE,
                                      width=right-left+2*MERGE_CLEARANCE,height=bottom-top+2*MERGE_CLEARANCE)))
    return zones


def junction_conflicts(paths, zones):
    return {rel for rel,(points,_,_) in paths.items()
            if any(key not in endpoint_keys(rel) and any(hits_rect(a,b,rect) for a,b in zip(points,points[1:]))
                   for key,rect in zones)}


def simplify_paths(positioned, paths):
    """Remove obsolete doglegs after repair, validating the resulting shared topology."""
    paths=dict(paths)
    aprons=port_aprons(positioned)
    zones=merge_junctions(positioned,paths)
    conflict_limit=len(junction_conflicts(paths,zones))
    for _ in range(2):
        changed=False
        for rel in sorted(paths,key=lambda r:(r.child,r.column,r.parent,r.parent_column)):
            for _ in range(4):
                original,cs,ps=paths[rel]
                keys=endpoint_keys(rel)
                rows=endpoint_rows(positioned,rel)
                others=[p for other,(p,_,_) in paths.items() if not keys&endpoint_keys(other)]
                overlap=sum(overlap_length(original,p) for p in others)
                candidates=[]
                for first in range(len(original)-3):
                    for last in range(first+3,len(original)):
                        a,b=original[first],original[last]
                        middles=[()] if a[0]==b[0] or a[1]==b[1] else [((a[0],b[1]),),((b[0],a[1]),)]
                        for middle in middles:
                            trial=compact((*original[:first+1],*middle,*original[last:]))
                            if len(trial)>=len(original):continue
                            # Keep the cardinality markers horizontal at their exact ports.
                            if not (trial[1][1]==trial[0][1] and (trial[1][0]-trial[0][0])*cs>0 and
                                    trial[-2][1]==trial[-1][1] and (trial[-2][0]-trial[-1][0])*ps>0):continue
                            candidates.append(trial)
                candidates=sorted(set(candidates),key=lambda p:(len(p),sum(abs(a[0]-b[0])+abs(a[1]-b[1])
                                  for a,b in zip(p,p[1:])),p))
                accepted=False
                for trial in candidates:
                    interior=trim_ports(trial)
                    if any(hits_rect(a,b,item.rect,8 if item.table.name in (rel.child,rel.parent) else 12)
                           for a,b in zip(interior,interior[1:]) for item in positioned):continue
                    if any(not apron_allows(a,b,[name for name,r in aprons if hits_rect(a,b,r)],rows)
                           for a,b in zip(interior,interior[1:])):continue
                    if any(key not in keys and any(hits_rect(a,b,r) for a,b in zip(trial,trial[1:]))
                           for key,r in zones):continue
                    if sum(overlap_length(trial,p) for p in others)>overlap+1e-6:continue
                    candidate=dict(paths)
                    candidate[rel]=trial,cs,ps
                    new_zones=merge_junctions(positioned,candidate)
                    conflicts=len(junction_conflicts(candidate,new_zones))
                    if conflicts>conflict_limit:continue
                    paths,zones,conflict_limit=candidate,new_zones,conflicts
                    accepted=changed=True
                    break
                if not accepted:break
        if not changed:break
    return paths


def bundle_common_routes(positioned, paths, tolerance=12):
    """Coalesce almost coincident trunks with the SAME endpoint, never different keys.

    Reuse an existing route to the common port rather than drawing subpixel parallel
    tracks and hairpins. New attachments must preserve the collision-free merge graph.
    """
    paths=dict(paths)
    aprons=port_aprons(positioned)
    zones=merge_junctions(positioned,paths)
    conflict_limit=len(junction_conflicts(paths,zones))
    def length(points):
        return sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(points,points[1:]))
    for _ in range(2):
        groups={}
        for rel,(_,cs,ps) in paths.items():
            groups.setdefault((rel.child,rel.column,cs),[]).append((rel,False))
            groups.setdefault((rel.parent,rel.parent_column,ps),[]).append((rel,True))
        changed=False
        for key,members in sorted(groups.items()):
            if len(members)<2:continue
            for rel,reverse in sorted(members,key=lambda item:(item[0].child,item[0].column,item[0].parent,item[0].parent_column)):
                original,cs,ps=paths[rel]
                outward=tuple(reversed(original)) if reverse else original
                keys=endpoint_keys(rel)
                rows=endpoint_rows(positioned,rel)
                others=[p for other,(p,_,_) in paths.items() if not keys&endpoint_keys(other)]
                old_overlap=sum(overlap_length(original,p) for p in others)
                candidates={}
                targets=[(index,p) for index,p in enumerate(outward[1:],1)]
                for index,(a,b) in enumerate(zip(outward,outward[1:]),1):
                    span=abs(b[0]-a[0])+abs(b[1]-a[1])
                    for distance in (24,48,span-24,span-48):
                        if 0<distance<span:
                            targets.append((index,tuple(a[k]+(b[k]-a[k])*distance/span for k in (0,1))))
                for reference,ref_reverse in members:
                    if reference==rel:continue
                    ref=paths[reference][0]
                    ref=tuple(reversed(ref)) if ref_reverse else ref
                    old_exclusive=length(outward)-overlap_length(outward,ref)
                    for index,point in targets:
                        for segment,(a,b) in enumerate(zip(ref,ref[1:])):
                            if a[1]==b[1]:
                                join=(max(min(point[0],max(a[0],b[0])),min(a[0],b[0])),a[1])
                            else:
                                join=(a[0],max(min(point[1],max(a[1],b[1])),min(a[1],b[1])))
                            distance=abs(join[0]-point[0])+abs(join[1]-point[1])
                            if distance>tolerance or (join[0]!=point[0] and join[1]!=point[1]):continue
                            candidate=compact((*ref[:segment+1],join,point,*outward[index:]))
                            gain=old_exclusive-(length(candidate)-overlap_length(candidate,ref))
                            if gain<=tolerance or length(candidate)>length(outward)+48:continue
                            trial=tuple(reversed(candidate)) if reverse else candidate
                            if trial==original:continue
                            if not (trial[1][1]==trial[0][1] and (trial[1][0]-trial[0][0])*cs>0 and
                                    trial[-2][1]==trial[-1][1] and (trial[-2][0]-trial[-1][0])*ps>0):continue
                            candidates[trial]=max(candidates.get(trial,0),gain)
                for trial,gain in sorted(candidates.items(),key=lambda item:(-item[1],len(item[0]),item[0]))[:32]:
                    if len(set(trial))!=len(trial):continue
                    if any(crosses(a,b,c,d) or overlap_length((a,b),(c,d))>0
                           for i,(a,b) in enumerate(zip(trial,trial[1:]))
                           for c,d in zip(trial[i+2:],trial[i+3:])):continue
                    interior=trim_ports(trial)
                    if any(hits_rect(a,b,item.rect,8 if item.table.name in (rel.child,rel.parent) else 12)
                           for a,b in zip(interior,interior[1:]) for item in positioned):continue
                    if any(not apron_allows(a,b,[name for name,r in aprons if hits_rect(a,b,r)],rows)
                           for a,b in zip(interior,interior[1:])):continue
                    if any(owner not in keys and any(hits_rect(a,b,r) for a,b in zip(trial,trial[1:]))
                           for owner,r in zones):continue
                    if sum(overlap_length(trial,p) for p in others)>old_overlap+1e-6:continue
                    candidate=dict(paths)
                    candidate[rel]=trial,cs,ps
                    new_zones=merge_junctions(positioned,candidate)
                    conflicts=len(junction_conflicts(candidate,new_zones))
                    if conflicts>conflict_limit:continue
                    paths,zones,conflict_limit=candidate,new_zones,conflicts
                    changed=True
                    break
        if not changed:break
    return paths


def canonicalize_shared_trees(positioned, paths, clearance_weight=1000):
    """Use one rooted shortest-path tree for each common port, eliminating diamonds.

    Edges come only from the existing route union; intersections are split explicitly.
    Thus alternate routes cannot split and rejoin the same shared trunk repeatedly.
    """
    paths=dict(paths)
    limit=len(junction_conflicts(paths,merge_junctions(positioned,paths)))
    groups={}
    for rel,(_,cs,ps) in paths.items():
        groups.setdefault((rel.child,rel.column,cs),[]).append((rel,False))
        groups.setdefault((rel.parent,rel.parent_column,ps),[]).append((rel,True))
    for key,members in sorted(groups.items()):
        if len(members)<2:continue
        routes=[tuple(reversed(paths[r][0])) if reverse else paths[r][0] for r,reverse in members]
        root=routes[0][0]
        segments=[(a,b) for points in routes for a,b in zip(points,points[1:])]
        nodes={p for route in routes for p in route}
        for a,b in segments:
            if a[1]!=b[1]:continue
            for c,d in segments:
                if c[0]==d[0] and min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(c[1],d[1])<=a[1]<=max(c[1],d[1]):
                    nodes.add((c[0],a[1]))
        graph={p:{} for p in nodes}
        for a,b in segments:
            if a[1]==b[1]:
                split=sorted(p for p in nodes if p[1]==a[1] and min(a[0],b[0])<=p[0]<=max(a[0],b[0]))
            else:
                split=sorted(p for p in nodes if p[0]==a[0] and min(a[1],b[1])<=p[1]<=max(a[1],b[1]))
            for p,q in zip(split,split[1:]):
                distance=abs(p[0]-q[0])+abs(p[1]-q[1])
                graph[p][q]=graph[q][p]=distance
        # Prefer branch sites with room around them. Pure length alone picks a nearby
        # track through another group's traffic and recreates a cramped join.
        foreign_segments=[(a,b) for rel,(points,_,_) in paths.items() if key not in endpoint_keys(rel)
                          for a,b in zip(points,points[1:])]
        template=positioned[0].rect
        penalties={p:clearance_weight if any(hits_rect(a,b,replace(template,x=p[0]-MERGE_CLEARANCE,y=p[1]-MERGE_CLEARANCE,
                                                     width=2*MERGE_CLEARANCE,height=2*MERGE_CLEARANCE))
                                for a,b in foreign_segments) else 0 for p in nodes}
        distance={root:0.}
        parent={root:None}
        queue=[(0.,root)]
        while queue:
            cost,p=heapq.heappop(queue)
            if cost!=distance[p]:continue
            for q,weight in sorted(graph[p].items()):
                value=cost+weight+penalties[q]
                if value<distance.get(q,math.inf)-1e-9:
                    distance[q]=value
                    parent[q]=p
                    heapq.heappush(queue,(value,q))
        candidate=dict(paths)
        valid=True
        for (rel,reverse),original in zip(members,routes):
            p=original[-1]
            result=[]
            while p is not None:
                result.append(p)
                p=parent[p]
            # result runs from the other port to this group's root.
            trial=compact(result if reverse else tuple(reversed(result)))
            _,cs,ps=paths[rel]
            if not (trial[1][1]==trial[0][1] and (trial[1][0]-trial[0][0])*cs>0 and
                    trial[-2][1]==trial[-1][1] and (trial[-2][0]-trial[-1][0])*ps>0):
                valid=False
                break
            candidate[rel]=trial,cs,ps
        if not valid:
            logging.getLogger(__name__).debug('Shared tree %s rejected: endpoint direction',key)
            continue
        zones=merge_junctions(positioned,candidate)
        conflicts=len(junction_conflicts(candidate,zones))
        logging.getLogger(__name__).debug('Shared tree %s: %d crossing routes',key,conflicts)
        if conflicts:
            logging.getLogger(__name__).debug('  %s',[(r.child,r.column,r.parent,r.parent_column)
                                                     for r in junction_conflicts(candidate,zones)])
            # Adopt independent safe branches even if another part of this large
            # group's tree would intersect a foreign merge zone.
            partial=dict(paths)
            for rel,_ in sorted(members,key=lambda item:(item[0].child,item[0].column,item[0].parent,item[0].parent_column)):
                trial=dict(partial)
                trial[rel]=candidate[rel]
                trial_zones=merge_junctions(positioned,trial)
                if len(junction_conflicts(trial,trial_zones))<=limit:
                    partial=trial
            candidate=partial
            zones=merge_junctions(positioned,candidate)
            conflicts=len(junction_conflicts(candidate,zones))
        if conflicts<=limit:
            paths,limit=candidate,conflicts
    return paths


def protect_merge_junctions(positioned, paths, rounds=24):
    """Reroute only foreign traffic through a merge, recomputing joins after each pass."""
    paths=dict(paths)
    forbidden_turns=[]
    best=dict(paths)
    best_count=math.inf
    for iteration in range(rounds):
        zones=merge_junctions(positioned,paths)
        conflicts=junction_conflicts(paths,zones)
        if len(conflicts)<best_count:
            best,best_count=dict(paths),len(conflicts)
        logging.getLogger(__name__).debug('Merge repair %d: %d zones, %d crossing routes',iteration,len(zones),len(conflicts))
        if not conflicts:
            break
        router=Router(positioned,list(paths),junctions=zones,
                      extra_points=[point for points,_,_ in paths.values() for point in points],no_turns=forbidden_turns)
        for points,_,_ in paths.values():
            router.add_usage(points[1:-1],1)
        for rel in sorted(conflicts,key=lambda r:(r.child,r.column,r.parent,r.parent_column)):
            old=paths[rel]
            router.add_usage(old[0][1:-1],-1)
            try:
                paths[rel]=router.route(rel)
            except ValueError as error:
                if not str(error).startswith('No obstacle-free route:'):
                    raise
                # A merge can occupy a neighbour's only terminal corridor. Move its
                # branches instead: the trunk may pass through, but may not turn here.
                blocked=[(key,rect) for key,rect in zones if key not in endpoint_keys(rel) and
                         any(hits_rect(a,b,rect) for a,b in zip(old[0],old[0][1:]))]
                owners={key for key,_ in blocked}
                forbidden_turns.extend(z for z in blocked if z not in forbidden_turns)
                mover=Router(positioned,list(paths),no_turns=forbidden_turns,
                             extra_points=[p for points,_,_ in paths.values() for p in points])
                for points,_,_ in paths.values():mover.add_usage(points[1:-1],1)
                for owner in sorted(paths,key=lambda r:(r.child,r.column,r.parent,r.parent_column)):
                    if endpoint_keys(owner)&owners:
                        mover.add_usage(paths[owner][0][1:-1],-1)
                        paths[owner]=mover.route(owner)
                        mover.add_usage(paths[owner][0][1:-1],1)
                break
            router.add_usage(paths[rel][0][1:-1],1)
    if len(junction_conflicts(paths,merge_junctions(positioned,paths)))>best_count:
        paths=best
    # Final lane separation may move interior runs, but must keep every terminal
    # branch point fixed and respect the protected zones. Topology cannot regress.
    zones=merge_junctions(positioned,paths)
    separated=separate_lanes(positioned,paths,junctions=zones,no_turns=forbidden_turns,keep_merges=True)
    return separated,merge_junctions(positioned,separated)


def separate_lanes(positioned, paths, spacing=6, junctions=(), no_turns=(), keep_merges=False, preserve_end_bends=True):
    """Nudge individual orthogonal runs into clear parallel lanes, retaining FK ports.

    A small terminal fan connects each lane to the original column row. Every proposed
    polyline is checked against ALL cards (including its own endpoints beyond the stub).
    Coordinate descent only accepts less overlap; it cannot trade card collisions for lanes.
    """
    occupied = {0: {}, 1: {}}
    aprons=port_aprons(positioned)

    def segments(points):
        for a,b in zip(points,points[1:]):
            axis=0 if a[1]==b[1] else 1
            yield axis,a[1-axis],min(a[axis],b[axis]),max(a[axis],b[axis])

    def cost(points):
        overlap=0.
        for axis,coordinate,lo,hi in segments(trim_ports(points)):
            for track,intervals in occupied[axis].items():
                distance=abs(track-coordinate)
                if distance < spacing:
                    overlap += sum(max(0,min(hi,end)-max(lo,start)) for start,end in intervals)*(1-distance/spacing)
        length=sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(points,points[1:]))
        return overlap*100+length*.01+len(points)*.1

    def clear(points, rel):
        interior=trim_ports(points)
        rows=endpoint_rows(positioned,rel)
        for a,b in zip(interior,interior[1:]):
            if any(hits_rect(a,b,item.rect,8 if item.table.name in (rel.child,rel.parent) else 12)
                   for item in positioned):
                return False
            if not apron_allows(a,b,[name for name,rect in aprons if hits_rect(a,b,rect)],rows):
                return False
            if any(key not in endpoint_keys(rel) and hits_rect(a,b,rect) for key,rect in junctions):
                return False
            if a[0]==b[0] and any(key in endpoint_keys(rel) and hits_rect(a,b,rect) for key,rect in no_turns):
                return False
        return True

    result={}
    for rel,(original,cs,ps) in paths.items():
        axes=[0 if a[1]==b[1] else 1 for a,b in zip(original,original[1:])]
        bases=[a[1-axis] for a,axis in zip(original,axes)]
        coords=list(bases)
        locked=set()
        if keep_merges:
            owned=[rect for key,rect in junctions if key in endpoint_keys(rel)]
            for index,(a,b) in enumerate(zip(original,original[1:])):
                if any(hits_rect(a,b,rect) for rect in owned):
                    locked.update((index-1,index,index+1))

        def build(values):
            # Terminal fans keep the crow's foot horizontal and the port on its exact row.
            start,end=original[0],original[-1]
            first=(start[0]+cs*12,start[1])
            last=(end[0]+ps*12,end[1])
            points=[start,first,(first[0],values[0])]
            for i in range(len(axes)-1):
                points.append((values[i+1],values[i]) if axes[i]==0 else (values[i],values[i+1]))
            points.extend(((last[0],values[-1]),last,end))
            return compact(points)

        current=original
        best=cost(current)
        for _ in range(2):
            changed=False
            for index,base in enumerate(bases):
                if index in locked:
                    continue
                chosen=coords[index]
                for offset in (0,*[sign*n*spacing for n in range(1,11) for sign in (-1,1)]):
                    trial=coords[:]
                    trial[index]=base+offset
                    points=build(trial)
                    if keep_merges and preserve_end_bends and (points[1]!=original[1] or points[-2]!=original[-2]):
                        continue
                    score=cost(points)
                    if score < best-1e-6 and clear(points,rel):
                        current,best,chosen=points,score,trial[index]
                if chosen != coords[index]:
                    coords[index]=chosen
                    changed=True
            if not changed:
                break
        result[rel]=current,cs,ps
        for axis,coordinate,lo,hi in segments(trim_ports(current)):
            occupied[axis].setdefault(coordinate,[]).append((lo,hi))
    return result


def separate_unrelated_trunks(positioned, paths):
    """Separate false shared stems after bundling, keeping true junction segments fixed."""
    zones=merge_junctions(positioned,paths)
    limit=len(junction_conflicts(paths,zones))
    proposed=separate_lanes(positioned,paths,junctions=zones,keep_merges=True,preserve_end_bends=False)
    if len(junction_conflicts(proposed,merge_junctions(positioned,proposed)))<=limit:
        return proposed
    # A private bend can become a new join after a shift. Adopt only topology-safe moves.
    result=dict(paths)
    for rel in sorted(paths,key=lambda r:(r.child,r.column,r.parent,r.parent_column)):
        if paths[rel]==proposed[rel]:continue
        trial=dict(result)
        trial[rel]=proposed[rel]
        if len(junction_conflicts(trial,merge_junctions(positioned,trial)))<=limit:
            result=trial
    return result


def corner_key(before,point,after):
    def direction(other):
        dx,dy=other[0]-point[0],other[1]-point[1]
        length=math.hypot(dx,dy)
        return (dx/length,dy/length) if length else (0.,0.)
    return point,tuple(sorted((direction(before),direction(after))))


def shared_corner_radii(paths, positioned=None, zones=()):
    radii={}
    for points,_,_ in paths.values():
        for a,b,c in zip(points,points[1:],points[2:]):
            radius=min(12,math.dist(a,b)*.45,math.dist(b,c)*.45)
            key=corner_key(a,b,c)
            radii[key]=min(radii.get(key,12),radius)
    if positioned is not None:
        aprons=port_aprons(positioned)
        for rel,(points,_,_) in paths.items():
            keys=endpoint_keys(rel)
            barriers=[replace(item.rect,x=item.rect.x-12,y=item.rect.y-12,
                              width=item.rect.width+24,height=item.rect.height+24)
                      for item in positioned if item.table.name not in (rel.child,rel.parent)]
            barriers.extend(rect for name,rect in aprons if name not in (rel.child,rel.parent))
            barriers.extend(rect for owner,rect in zones if owner not in keys)
            barriers.extend(replace(item.rect,x=item.rect.x-8,y=item.rect.y-8,
                                    width=item.rect.width+16,height=item.rect.height+16)
                            for item in positioned if item.table.name in (rel.child,rel.parent))
            for a,b,c in zip(points,points[1:],points[2:]):
                u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1])
                lu,lv=math.hypot(*u),math.hypot(*v)
                if not lu or not lv or abs(u[0]*v[0]+u[1]*v[1])>1e-6:continue
                key=corner_key(a,b,c)
                radius=radii[key]
                fitted=0.
                for _ in range(12):
                    entry=tuple(b[k]-u[k]/lu*radius for k in (0,1))
                    exit=tuple(b[k]+v[k]/lv*radius for k in (0,1))
                    left,right=min(entry[0],exit[0]),max(entry[0],exit[0])
                    top,bottom=min(entry[1],exit[1]),max(entry[1],exit[1])
                    if not any(left<=r.x+r.width and right>=r.x and top<=r.y+r.height and bottom>=r.y for r in barriers):
                        fitted=radius
                        break
                    radius/=2
                radii[key]=fitted
    return radii


def smooth_terminal_path(points, child_side, parent_side, positioned, child, parent,
                         grouped_start=False, grouped_end=False, junctions=(), own_junctions=(), corner_radii=None):
    """Replace crowded terminal staircases with tangent-continuous cubic fans.

    Only a bounded part of each endpoint is replaced. The convex hull of each cubic
    must clear every foreign card, so collision checks do not depend on sample density.
    Return both SVG commands and sampled geometry for the usual layout measurements.
    """
    barriers=[(item.table.name,replace(item.rect,x=item.rect.x-12,y=item.rect.y-12,
                                      width=item.rect.width+24,height=item.rect.height+24)) for item in positioned]
    barriers.extend(port_aprons(positioned))
    # Foreign merge zones are supplied already filtered by exact endpoint identity.
    barriers.extend(('',rect) for _,rect in junctions)

    def terminal(outward, side, own):
        port=outward[0]
        # Keep a horizontal stub for the cardinality marker, even on a curved fan.
        stub=(port[0]+side*12,port[1])
        # Individual endpoint smoothing must stop BEFORE the first shared junction.
        # Otherwise the same trunk corner gets different geometry on every edge.
        fan_limit=math.inf
        walked=0.
        for a,b in zip(outward,outward[1:]):
            length=math.dist(a,b)
            axis=0 if a[1]==b[1] else 1
            delta=b[axis]-a[axis]
            if not delta:continue
            for _,rect in own_junctions:
                if hits_rect(a,b,rect):
                    lo=rect.x if axis==0 else rect.y
                    hi=lo+(rect.width if axis==0 else rect.height)
                    entry=max(0,min((lo-a[axis])/delta,(hi-a[axis])/delta))
                    fan_limit=min(fan_limit,walked+entry*length-32)
            walked+=length
        for budget in (420,360,300,240,192,144,120,96,72,48):
            if budget>fan_limit:continue
            remaining=budget
            for index,(a,b) in enumerate(zip(outward,outward[1:])):
                length=abs(b[0]-a[0])+abs(b[1]-a[1])
                if length < remaining:
                    remaining-=length
                    continue
                anchor=(a[0]+(b[0]-a[0])*remaining/length,a[1]+(b[1]-a[1])*remaining/length)
                if ((anchor[0]-stub[0])*side < max(24,abs(anchor[1]-stub[1])*.9) or
                        abs(anchor[1]-stub[1]) < 1):
                    break
                dx,dy=anchor[0]-stub[0],anchor[1]-stub[1]
                c1=(stub[0]+dx*.65,stub[1])
                c2=((stub[0]+dx*.35,anchor[1]) if a[1]==b[1]
                    else (anchor[0],stub[1]+dy*.35))
                # The fan must join the remaining route in its actual direction.
                # A returning horizontal run can otherwise create a 180-degree cusp.
                tangent=(anchor[0]-c2[0],anchor[1]-c2[1])
                forward=(b[0]-a[0],b[1]-a[1])
                if (tangent[0]*forward[0]+tangent[1]*forward[1] <= 0 or
                        remaining >= length-1e-6):
                    break
                hull=(stub,c1,c2,anchor)
                left,right=min(p[0] for p in hull),max(p[0] for p in hull)
                top,bottom=min(p[1] for p in hull),max(p[1] for p in hull)
                blocked=any(left <= rect.x+rect.width and right >= rect.x and
                            top <= rect.y+rect.height and bottom >= rect.y
                            for name,rect in barriers if name != own)
                if not blocked:
                    samples=[]
                    for step in range(25):
                        t=step/24
                        samples.append(tuple((1-t)**3*stub[k]+3*(1-t)**2*t*c1[k]+
                                             3*(1-t)*t*t*c2[k]+t**3*anchor[k] for k in (0,1)))
                    return (port,stub,c1,c2,anchor),tuple(samples),index
                break
        return None

    start=None if grouped_start else terminal(points,child_side,child)
    # Reserve the start's untouched suffix before processing the opposite endpoint.
    body=points
    if start:
        fan,_,index=start
        body=(fan[-1],*points[index+1:])
    end=None if grouped_end else terminal(tuple(reversed(body)),parent_side,parent)
    middle=body
    if end:
        fan,_,index=end
        middle=(*body[:len(body)-index-1],fan[-1])
    commands=['M %g %g' % points[0]]
    geometry=[points[0]]
    if start:
        fan,samples,_=start
        commands.extend(('L %g %g' % fan[1],'C %g %g %g %g %g %g' % (*fan[2],*fan[3],*fan[4])))
        geometry.extend(samples)
    # Shared endpoints keep one horizontal trunk. Round the remote branches locally
    # instead of fanning every edge independently across neighbouring key entrances.
    skip_until=0
    for index,point in enumerate(middle[1:],1):
        if index<skip_until:continue
        if index+1 < len(middle):
            before,after=middle[index-1],middle[index+1]
            u=(point[0]-before[0],point[1]-before[1])
            v=(after[0]-point[0],after[1]-point[1])
            lu,lv=math.hypot(*u),math.hypot(*v)
            if (index+2<len(middle) and 0<lv<=4 and lu and
                    not any(hits_rect(point,after,rect) for _,rect in own_junctions)):
                following=middle[index+2]
                w=(following[0]-after[0],following[1]-after[1])
                lw=math.hypot(*w)
                if lw and abs(u[0]*v[0]+u[1]*v[1])<1e-6 and u[0]*w[0]+u[1]*w[1]>0:
                    # A subpixel lane change needs one gentle S, not two tiny elbows.
                    for budget in (48,24,12,6):
                        blend=min(budget,lu*.45,lw*.45)
                        entry=tuple(point[k]-u[k]/lu*blend for k in (0,1))
                        exit=tuple(after[k]+w[k]/lw*blend for k in (0,1))
                        left,right=min(entry[0],exit[0]),max(entry[0],exit[0])
                        top,bottom=min(entry[1],exit[1]),max(entry[1],exit[1])
                        foreign=any(left<=r.x+r.width and right>=r.x and top<=r.y+r.height and bottom>=r.y
                                    for name,r in barriers if name not in (child,parent))
                        own=any(left<=i.rect.x+i.rect.width+8 and right>=i.rect.x-8 and
                                top<=i.rect.y+i.rect.height+8 and bottom>=i.rect.y-8
                                for i in positioned if i.table.name in (child,parent))
                        if foreign or own:continue
                        commands.extend(('L %g %g' % entry,'C %g %g %g %g %g %g' % (*point,*after,*exit)))
                        geometry.append(entry)
                        for step in range(1,13):
                            t=step/12
                            geometry.append(tuple((1-t)**3*entry[k]+3*(1-t)**2*t*point[k]+
                                                  3*(1-t)*t*t*after[k]+t**3*exit[k] for k in (0,1)))
                        skip_until=index+2
                        break
                    if skip_until==index+2:continue
            if lu and lv and abs(u[0]*v[0]+u[1]*v[1])<1e-6:
                radius=min((corner_radii or {}).get(corner_key(before,point,after),12),lu*.45,lv*.45)
                entry=tuple(point[k]-u[k]/lu*radius for k in (0,1))
                exit=tuple(point[k]+v[k]/lv*radius for k in (0,1))
                c1=tuple(entry[k]+u[k]/lu*radius*.55228475 for k in (0,1))
                c2=tuple(exit[k]-v[k]/lv*radius*.55228475 for k in (0,1))
                left,right=min(entry[0],exit[0]),max(entry[0],exit[0])
                top,bottom=min(entry[1],exit[1]),max(entry[1],exit[1])
                foreign=any(left<=r.x+r.width and right>=r.x and top<=r.y+r.height and bottom>=r.y
                            for name,r in barriers if name not in (child,parent))
                own=any(left<=i.rect.x+i.rect.width+8 and right>=i.rect.x-8 and
                        top<=i.rect.y+i.rect.height+8 and bottom>=i.rect.y-8
                        for i in positioned if i.table.name in (child,parent))
                if radius>1e-6 and not foreign and not own:
                    commands.extend(('L %g %g' % entry,'C %g %g %g %g %g %g' % (*c1,*c2,*exit)))
                    geometry.append(entry)
                    for step in range(1,9):
                        t=step/8
                        geometry.append(tuple((1-t)**3*entry[k]+3*(1-t)**2*t*c1[k]+
                                              3*(1-t)*t*t*c2[k]+t**3*exit[k] for k in (0,1)))
                    continue
        commands.append('L %g %g' % point)
        geometry.append(point)
    if end:
        fan,samples,_=end
        commands.extend(('C %g %g %g %g %g %g' % (*fan[3],*fan[2],*fan[1]),'L %g %g' % fan[0]))
        geometry.extend(reversed(samples[:-1]))
        geometry.append(fan[0])
    return ' '.join(commands),tuple(geometry)


def rounded_orthogonal_path(points, corner_radii, default_radius=12):
    """Render an orthogonal route as line segments with short rounded corners."""
    if len(points) < 2:
        return ''
    commands=['M %g %g' % points[0]]
    for index, point in enumerate(points[1:-1], start=1):
        previous, following=points[index-1],points[index+1]
        incoming=(point[0]-previous[0],point[1]-previous[1])
        outgoing=(following[0]-point[0],following[1]-point[1])
        incoming_length=math.hypot(*incoming)
        outgoing_length=math.hypot(*outgoing)
        if not incoming_length or not outgoing_length or abs(incoming[0]*outgoing[0]+incoming[1]*outgoing[1]) > 1e-6:
            commands.append('L %g %g' % point)
            continue
        radius=min(corner_radii.get(corner_key(previous,point,following),default_radius),
                   incoming_length/2,outgoing_length/2)
        if radius <= 0:
            commands.append('L %g %g' % point)
            continue
        entry=(point[0]-incoming[0]/incoming_length*radius,point[1]-incoming[1]/incoming_length*radius)
        exit=(point[0]+outgoing[0]/outgoing_length*radius,point[1]+outgoing[1]/outgoing_length*radius)
        commands.extend(('L %g %g' % entry,'Q %g %g %g %g' % (*point,*exit)))
    commands.append('L %g %g' % points[-1])
    return ' '.join(commands)


class Router:
    """Shared rectilinear visibility grid; geometric edge checks are cached across routes."""
    def __init__(self, positioned, relations, clearance=12, gap=24, junctions=(), extra_points=(), no_turns=()):
        self.items={item.table.name:item for item in positioned}
        self.clearance,self.gap=clearance,gap
        self.aprons=port_aprons(positioned)
        self.junctions=junctions
        self.no_turns=no_turns
        self.xs=sorted({x for item in positioned for x in (item.rect.x-gap,item.rect.x+item.rect.width+gap)} |
                       {x for _,r in self.aprons for x in (r.x-12,r.x+r.width+12)} |
                       {x for _,r in junctions for x in (r.x-6,r.x+r.width+6)} |
                       {x for _,r in no_turns for x in (r.x-6,r.x+r.width+6)} |
                       {p[0] for p in extra_points} |
                       {min(i.rect.x for i in positioned)-192,max(i.rect.x+i.rect.width for i in positioned)+192})
        ys={y for item in positioned for y in (item.rect.y-gap,item.rect.y+item.rect.height+gap)}
        ys.update(y for _,r in self.aprons for y in (r.y-12,r.y+r.height+12))
        ys.update(y for _,r in junctions for y in (r.y-6,r.y+r.height+6))
        ys.update(y for _,r in no_turns for y in (r.y-6,r.y+r.height+6))
        ys.update(p[1] for p in extra_points)
        for rel in relations:
            ys.add(self.port(rel.child,rel.column,-1)[1])
            ys.add(self.port(rel.parent,rel.parent_column,-1)[1])
        self.ys=sorted(ys)
        self.nx=len(self.xs)
        self.xi={x:i for i,x in enumerate(self.xs)}
        self.yi={y:i for i,y in enumerate(self.ys)}
        self.geometry={}
        self.penalties={}

    def port(self, name, column, side):
        item=self.items[name]
        row=next(i for i,c in enumerate(item.table.columns) if c.name == column)
        return item.rect.x+(item.rect.width if side>0 else 0),item.rect.y+34+(row+.5)*26

    def index(self,point):
        return self.yi[point[1]]*self.nx+self.xi[point[0]]

    def point(self,index):
        return self.xs[index%self.nx],self.ys[index//self.nx]

    def edge_key(self,a,b):
        return min(a,b),max(a,b)

    def clear(self,a,b,rows,keys):
        key=self.edge_key(a,b)
        if key not in self.geometry:
            p,q=self.point(a),self.point(b)
            clear=not any(hits_rect(p,q,item.rect,self.clearance) for item in self.items.values())
            self.geometry[key]=(clear,tuple(name for name,rect in self.aprons if hits_rect(p,q,rect)),
                                tuple(owner for owner,rect in self.junctions if hits_rect(p,q,rect)),
                                tuple(owner for owner,rect in self.no_turns if p[0]==q[0] and hits_rect(p,q,rect)))
        clear,hits,junction_hits,turn_hits=self.geometry[key]
        return (clear and apron_allows(self.point(a),self.point(b),hits,rows) and
                all(owner in keys for owner in junction_hits) and not any(owner in keys for owner in turn_hits))

    def add_usage(self,points,weight):
        # Grid coordinates contain each crossing. Split its penalty between the two
        # incident edges, so A* can't avoid paying merely by crossing at a grid vertex.
        def add(a,b,cost):
            key=self.edge_key(a,b)
            self.penalties[key]=self.penalties.get(key,0)+cost*weight
        for a,b in zip(points,points[1:]):
            ax,ay=self.xi[a[0]],self.yi[a[1]]
            bx,by=self.xi[b[0]],self.yi[b[1]]
            if ay == by:
                lo,hi=sorted((ax,bx))
                for x in range(lo,hi):
                    add(ay*self.nx+x,ay*self.nx+x+1,(self.xs[x+1]-self.xs[x])*.12)
                for x in range(lo+1,hi):
                    node=ay*self.nx+x
                    if ay: add(node-self.nx,node,90)
                    if ay+1<len(self.ys): add(node,node+self.nx,90)
            else:
                lo,hi=sorted((ay,by))
                for y in range(lo,hi):
                    add(y*self.nx+ax,(y+1)*self.nx+ax,(self.ys[y+1]-self.ys[y])*.12)
                for y in range(lo+1,hi):
                    node=y*self.nx+ax
                    if ax: add(node-1,node,90)
                    if ax+1<self.nx: add(node,node+1,90)

    def route(self,rel):
        rows=endpoint_rows(list(self.items.values()),rel)
        keys=endpoint_keys(rel)
        starts,goals={},{}
        for side in (-1,1):
            p=self.port(rel.child,rel.column,side)
            stub=(p[0]+side*self.gap,p[1])
            if not any(key not in keys and hits_rect(p,stub,rect) for key,rect in self.junctions):
                starts[self.index(stub)]=side
            p=self.port(rel.parent,rel.parent_column,side)
            stub=(p[0]+side*self.gap,p[1])
            if not any(key not in keys and hits_rect(p,stub,rect) for key,rect in self.junctions):
                goals[self.index(stub)]=side
        if not starts or not goals:
            raise ValueError(f'No obstacle-free route: {rel.child}.{rel.column} -> {rel.parent}.{rel.parent_column}')
        goal_points=[self.point(node) for node in goals]
        def heuristic(node):
            x,y=self.point(node)
            return min(abs(x-gx)+abs(y-gy) for gx,gy in goal_points)
        queue=[]
        distance={}
        previous={}
        for node in starts:
            state=node*2  # 0 = horizontal, 1 = vertical
            distance[state]=self.gap
            previous[state]=None
            heapq.heappush(queue,(self.gap+heuristic(node),self.gap,state))
        while queue:
            _,cost,state=heapq.heappop(queue)
            if cost != distance.get(state):
                continue
            node,direction=divmod(state,2)
            if node in goals:
                result=[]
                cursor=state
                while cursor is not None:
                    result.append(self.point(cursor//2))
                    cursor=previous[cursor]
                result.reverse()
                start_side=starts[self.index(result[0])]
                end_side=goals[node]
                return compact((self.port(rel.child,rel.column,start_side),*result,
                                self.port(rel.parent,rel.parent_column,end_side))),start_side,end_side
            x,y=node%self.nx,node//self.nx
            neighbours=[]
            if x: neighbours.append((node-1,0))
            if x+1<self.nx: neighbours.append((node+1,0))
            if y: neighbours.append((node-self.nx,1))
            if y+1<len(self.ys): neighbours.append((node+self.nx,1))
            p=self.point(node)
            for other,axis in neighbours:
                if not self.clear(node,other,rows,keys):
                    continue
                q=self.point(other)
                candidate=cost+abs(p[0]-q[0])+abs(p[1]-q[1])+(24 if axis!=direction else 0)
                candidate+=max(0,self.penalties.get(self.edge_key(node,other),0))
                target=other*2+axis
                if candidate < distance.get(target,math.inf):
                    distance[target]=candidate
                    previous[target]=state
                    heapq.heappush(queue,(candidate+heuristic(other),candidate,target))
        raise ValueError(f'No obstacle-free route: {rel.child}.{rel.column} -> {rel.parent}.{rel.parent_column}')


def route_all(positioned, relations, passes, factory, evaluate=None):
    router=Router(positioned,relations)
    # Short links first leave long links enough freedom to choose other corridors.
    ordered=sorted(relations,key=lambda r:(abs(router.items[r.child].rect.center[0]-router.items[r.parent].rect.center[0])+
                                          abs(router.items[r.child].rect.center[1]-router.items[r.parent].rect.center[1]),
                                          r.child,r.column,r.parent,r.parent_column))
    paths={}
    best=None
    best_score=None
    best_paths=None
    for iteration in range(passes):
        for rel in ordered:
            if rel in paths:
                router.add_usage(paths[rel][0][1:-1],-1)
            points,cs,ps=router.route(rel)
            paths[rel]=points,cs,ps
            router.add_usage(points[1:-1],1)
        candidate=[factory(rel,*paths[rel]) for rel in ordered]
        score=evaluate(candidate) if evaluate else iteration*-1
        if best_score is None or score < best_score:
            best,best_score=candidate,score
            best_paths=dict(paths)
    if not best:
        return []
    # Route choice and lane separation solve different problems: routing avoids cards;
    # lane assignment prevents unrelated keys from looking like one shared bus.
    separated=separate_lanes(positioned,best_paths)
    separated,_=protect_merge_junctions(positioned,separated)
    separated=simplify_paths(positioned,separated)
    separated=bundle_common_routes(positioned,separated)
    separated=canonicalize_shared_trees(positioned,separated)
    separated=canonicalize_shared_trees(positioned,separated,clearance_weight=0)
    separated=separate_unrelated_trunks(positioned,separated)
    return [factory(rel,*separated[rel]) for rel in best_paths]
