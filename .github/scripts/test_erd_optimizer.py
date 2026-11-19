from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parent))
import db_schema as d
from erd_optimizer import LayoutOptions, hits_rect, optimize_grid, route_all, overlap_length, separate_lanes, trim_ports, smooth_terminal_path, port_aprons
from erd_optimizer import (merge_junctions, junction_conflicts, protect_merge_junctions, simplify_paths,
                           bundle_common_routes, canonicalize_shared_trees, shared_corner_radii, corner_key,
                           separate_unrelated_trunks)


class OptimizerTest(unittest.TestCase):
    def test_different_keys_cannot_share_a_private_vertical_stem(self):
        media=d.Table('media',[d.Column('author_id','bigint'),d.Column('message_id','bigint')])
        profiles=d.Table('profiles',[d.Column('id','bigint')])
        messages=d.Table('messages',[d.Column('id','bigint')])
        placed=[d.PositionedTable(media,d.Rect(0,0,160,140)),
                d.PositionedTable(profiles,d.Rect(600,-300,160,140)),
                d.PositionedTable(messages,d.Rect(600,-100,160,140))]
        a=d.Relationship('media','author_id','profiles','id',False)
        b=d.Relationship('media','message_id','messages','id',False)
        paths={a:(((160,47),(340,47),(340,-253),(600,-253)),1,-1),
               b:(((160,73),(340,73),(340,-53),(600,-53)),1,-1)}
        self.assertGreater(overlap_length(paths[a][0],paths[b][0]),90)
        clean=separate_unrelated_trunks(placed,paths)
        self.assertEqual(0,overlap_length(clean[a][0],clean[b][0]))
        for rel,(points,_,_) in clean.items():
            self.assertEqual(paths[rel][0][0],points[0])
            self.assertEqual(paths[rel][0][-1],points[-1])
            for item in placed:
                if item.table.name not in (rel.child,rel.parent):
                    self.assertFalse(any(hits_rect(a,b,item.rect,12) for a,b in zip(points,points[1:])))

    def test_parallel_tracks_eight_units_apart_to_same_key_are_bundled(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('a','b','hub')}
        placed=[d.PositionedTable(tables['a'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['b'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['hub'],d.Rect(600,-400,160,140))]
        a=d.Relationship('a','id','hub','id',False)
        b=d.Relationship('b','id','hub','id',False)
        pa=((160,47),(348,47),(348,-100),(308,-100),(308,-353),(600,-353))
        pb=((600,47),(340,47),(340,-94),(300,-94),(300,-353),(600,-353))
        paths={a:(pa,1,-1),b:(pb,-1,-1)}
        clean=bundle_common_routes(placed,paths)
        self.assertGreater(overlap_length(clean[a][0],clean[b][0]),overlap_length(pa,pb)+100)
        self.assertEqual(set(),junction_conflicts(clean,merge_junctions(placed,clean)))

    def test_corner_radius_shrinks_to_fit_instead_of_leaving_a_square_corner(self):
        child=d.Table('child',[d.Column('id','bigint')])
        parent=d.Table('parent',[d.Column('id','bigint')])
        placed=[d.PositionedTable(child,d.Rect(0,0,160,140)),
                d.PositionedTable(parent,d.Rect(600,0,160,140))]
        rel=d.Relationship('child','id','parent','id',False)
        points=((160,47),(340,47),(340,-100),(420,-100),(420,47),(600,47))
        zones=[(('foreign','id',1),d.Rect(342,-96,2,2))]
        radii=shared_corner_radii({rel:(points,1,-1)},placed,zones)
        self.assertEqual(3,radii[corner_key(points[1],points[2],points[3])])
        path,geometry=smooth_terminal_path(points,1,-1,placed,'child','parent',True,True,
                                           junctions=zones,corner_radii=radii)
        self.assertNotIn('L 340 -100',path)
        self.assertFalse(any(hits_rect(a,b,zones[0][1]) for a,b in zip(geometry,geometry[1:])))

    def test_card_entrances_leave_a_wide_transport_corridor(self):
        a=d.Table('a',[d.Column('id','bigint')])
        b=d.Table('b',[d.Column('id','bigint')])
        placed=[d.PositionedTable(a,d.Rect(0,0,339,100)),d.PositionedTable(b,d.Rect(654,0,367,100))]
        aprons=port_aprons(placed)
        right=next(rect for name,rect in aprons if name=='a' and rect.x==339)
        left=next(rect for name,rect in aprons if name=='b' and rect.x+rect.width==654)
        self.assertGreaterEqual(left.x-(right.x+right.width),96)

    def test_foreign_line_near_merge_is_not_considered_clear(self):
        hub=d.Table('hub',[d.Column('id','bigint')])
        placed=[d.PositionedTable(hub,d.Rect(0,0,160,100))]
        a=d.Relationship('hub','id','a','id',False)
        b=d.Relationship('hub','id','b','id',False)
        foreign=d.Relationship('c','id','d','id',False)
        paths={a:(((160,47),(340,47),(340,-100),(600,-100)),1,-1),
               b:(((160,47),(400,47),(400,200),(600,200)),1,-1),
               foreign:(((356,0),(356,100)),1,1)}
        self.assertEqual({foreign},junction_conflicts(paths,merge_junctions(placed,paths)))

    def test_endpoint_smoothing_cannot_redraw_shared_trunk_differently(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('a','b','hub')}
        placed=[d.PositionedTable(tables['a'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['b'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['hub'],d.Rect(600,-400,160,140))]
        a=d.Relationship('a','id','hub','id',False)
        b=d.Relationship('b','id','hub','id',False)
        tail=((340,47),(340,-100),(300,-100),(300,-353),(600,-353))
        paths={a:(((160,47),*tail),1,-1),b:(((600,47),*tail),-1,-1)}
        zones=merge_junctions(placed,paths)
        radii=shared_corner_radii(paths)
        arcs=[]
        for rel,(points,cs,ps) in paths.items():
            _,geometry=smooth_terminal_path(points,cs,ps,placed,rel.child,rel.parent,False,True,
                                             own_junctions=zones,corner_radii=radii)
            arcs.append(tuple(p for p in geometry if 328<=p[0]<=340 and -100<=p[1]<=-88))
        self.assertGreater(len(arcs[0]),5)
        self.assertEqual(arcs[0],arcs[1])

    def test_shared_tree_prefers_a_join_clear_of_foreign_traffic(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('a','b','hub')}
        placed=[d.PositionedTable(tables['a'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['b'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['hub'],d.Rect(600,-400,160,140))]
        a=d.Relationship('a','id','hub','id',False)
        b=d.Relationship('b','id','hub','id',False)
        foreign=d.Relationship('c','id','d','id',False)
        paths={a:(((160,47),(340,47),(340,-100),(300,-100),(300,-353),(600,-353)),1,-1),
               b:(((600,47),(340,47),(340,-100),(320,-100),(320,-353),(600,-353)),-1,-1),
               foreign:(((320,-125),(320,-75)),1,1)}
        self.assertEqual({foreign},junction_conflicts(paths,merge_junctions(placed,paths)))
        clean=canonicalize_shared_trees(placed,paths)
        self.assertEqual(set(),junction_conflicts(clean,merge_junctions(placed,clean)))
        self.assertEqual(paths[foreign],clean[foreign])
        self.assertEqual(clean[a][0][1:],clean[b][0][1:])

    def test_shared_routes_cannot_split_and_rejoin_as_a_diamond(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('a','b','hub')}
        placed=[d.PositionedTable(tables['a'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['b'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['hub'],d.Rect(600,-400,160,140))]
        a=d.Relationship('a','id','hub','id',False)
        b=d.Relationship('b','id','hub','id',False)
        pa=((160,47),(340,47),(340,-100),(300,-100),(300,-353),(600,-353))
        pb=((600,47),(340,47),(340,-100),(302,-100),(302,-353),(600,-353))
        paths={a:(pa,1,-1),b:(pb,-1,-1)}
        clean=canonicalize_shared_trees(placed,paths)
        self.assertEqual(clean[a][0][1:],clean[b][0][1:])
        def total_length(mapping):
            return sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for p,_,_ in mapping.values() for a,b in zip(p,p[1:]))
        self.assertLess(total_length(clean),total_length(paths))
        self.assertEqual(set(),junction_conflicts(clean,merge_junctions(placed,clean)))
        self.assertEqual(clean,canonicalize_shared_trees(placed,clean))
        for rel,(points,_,_) in clean.items():
            self.assertEqual(paths[rel][0][0],points[0])
            self.assertEqual(paths[rel][0][-1],points[-1])

    def test_small_parallel_lane_change_is_one_gentle_curve(self):
        child=d.Table('child',[d.Column('id','bigint')])
        parent=d.Table('parent',[d.Column('id','bigint')])
        placed=[d.PositionedTable(child,d.Rect(0,0,160,140)),
                d.PositionedTable(parent,d.Rect(600,0,160,140))]
        points=((160,47),(340,47),(340,-50),(341,-50),(341,-100),(420,-100),(420,47),(600,47))
        path,geometry=smooth_terminal_path(points,1,-1,placed,'child','parent',True,True)
        def lane_shifts(svg_path):
            current=None
            result=[]
            for kind,raw in re.findall(r'([MLC])\s*([^MLC]+)',svg_path):
                values=list(map(float,raw.split()))
                end=tuple(values[-2:])
                if kind=='C' and values[1]==values[3] and 0<abs(values[0]-values[2])<=4:
                    result.append((current,end))
                current=end
            return result
        shifts=lane_shifts(path)
        self.assertEqual(1,len(shifts))
        self.assertGreaterEqual(abs(shifts[0][0][1]-shifts[0][1][1]),24)
        self.assertEqual(points[0],geometry[0])
        self.assertEqual(points[-1],geometry[-1])
        for a,b,c in zip(geometry,geometry[1:],geometry[2:]):
            self.assertGreaterEqual((b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]),-1e-6)
        guarded,_=smooth_terminal_path(points,1,-1,placed,'child','parent',True,True,
                                       own_junctions=[(('child','id',1),d.Rect(330,-55,20,10))])
        self.assertEqual([],lane_shifts(guarded))

    def test_subpixel_parallel_trunks_to_same_key_are_coalesced(self):
        tables={name:d.Table(name,[d.Column('id','bigint'),d.Column('other','bigint')]) for name in ('a','b','hub')}
        placed=[d.PositionedTable(tables['a'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['b'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['hub'],d.Rect(600,-400,160,140))]
        a=d.Relationship('a','id','hub','id',False)
        b=d.Relationship('b','id','hub','id',False)
        pa=((160,47),(340.075,47),(340.075,-100),(300,-100),(300,-353),(600,-353))
        pb=((600,47),(340,47),(340,-94),(300.5,-94),(300.5,-353),(600,-353))
        paths={a:(pa,1,-1),b:(pb,-1,-1)}
        result=bundle_common_routes(placed,paths)
        self.assertGreater(overlap_length(result[a][0],result[b][0]),overlap_length(pa,pb)+100)
        self.assertEqual(set(),junction_conflicts(result,merge_junctions(placed,result)))
        for rel,(points,_,_) in result.items():
            self.assertEqual(paths[rel][0][0],points[0])
            self.assertEqual(paths[rel][0][-1],points[-1])
        # Similar geometry with different referenced columns must never be bundled.
        other=d.Relationship('b','id','hub','other',False)
        different={a:paths[a],other:((*pb[:-1],(600,-327)),-1,-1)}
        self.assertEqual(different,bundle_common_routes(placed,different))

    def test_obsolete_dogleg_is_removed_but_necessary_card_bypass_remains(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('child','parent','blocker')}
        placed=[d.PositionedTable(tables['child'],d.Rect(0,0,160,140)),
                d.PositionedTable(tables['parent'],d.Rect(600,0,160,140)),
                d.PositionedTable(tables['blocker'],d.Rect(300,0,200,120))]
        rel=d.Relationship('child','id','parent','id',False)
        points=((160,47),(230,47),(230,-100),(330,-100),(330,-120),(380,-120),
                (380,-100),(550,-100),(550,47),(600,47))
        clean=simplify_paths(placed,{rel:(points,1,-1)})[rel][0]
        self.assertLess(len(clean),len(points))
        self.assertEqual(points[0],clean[0])
        self.assertEqual(points[-1],clean[-1])
        self.assertNotIn(-120,[p[1] for p in clean])
        self.assertFalse(any(hits_rect(a,b,placed[2].rect,12) for a,b in zip(clean,clean[1:])))
        self.assertGreaterEqual(len(clean),6)

    def test_intermediate_merge_is_detected_but_a_shared_elbow_is_not_a_merge(self):
        table=d.Table('hub',[d.Column('id','bigint')])
        positioned=[d.PositionedTable(table,d.Rect(0,0,160,100))]
        first=d.Relationship('hub','id','a','id',False)
        second=d.Relationship('hub','id','b','id',False)
        foreign=d.Relationship('c','id','d','id',False)
        paths={first:(((160,47),(340,47),(340,-100),(400,-100),(400,-200),(600,-200)),1,-1),
               second:(((160,47),(340,47),(340,-100),(500,-100),(500,200),(600,200)),1,-1)}
        # Only 'hub' has a shared endpoint, so other tables need no geometry here.
        zones=merge_junctions(positioned,paths)
        self.assertTrue(any(hits_rect((400,-100),(400,-100),rect) for _,rect in zones))
        self.assertFalse(any(hits_rect((340,47),(340,47),rect) for _,rect in zones))
        paths[foreign]=(((400,-300),(400,300)),1,1)
        self.assertEqual({foreign},junction_conflicts(paths,zones))

    def test_foreign_route_is_rerouted_around_merge_junction(self):
        tables={name:d.Table(name,[d.Column('id','bigint')]) for name in ('hub','a','b','c','d')}
        positions={'hub':(0,0),'a':(600,-147),'b':(600,153),'c':(100,-300),'d':(100,300)}
        placed=[d.PositionedTable(table,d.Rect(*positions[name],160,100)) for name,table in tables.items()]
        first=d.Relationship('hub','id','a','id',False)
        second=d.Relationship('hub','id','b','id',False)
        foreign=d.Relationship('c','id','d','id',False)
        paths={first:(((160,47),(340,47),(340,-100),(600,-100)),1,-1),
               second:(((160,47),(400,47),(400,200),(600,200)),1,-1),
               foreign:(((260,-253),(340,-253),(340,347),(260,347)),1,1)}
        zones=merge_junctions(placed,paths)
        self.assertEqual({foreign},junction_conflicts(paths,zones))
        self.assertTrue(any(hits_rect((328,47),(328,47),rect) for _,rect in zones))
        repaired,_=protect_merge_junctions(placed,paths)
        repaired=simplify_paths(placed,repaired)
        repaired=bundle_common_routes(placed,repaired)
        repaired=separate_unrelated_trunks(placed,repaired)
        self.assertEqual(set(paths),set(repaired))
        self.assertEqual(set(),junction_conflicts(repaired,merge_junctions(placed,repaired)))
        self.assertNotEqual(paths[foreign],repaired[foreign])
        for rel,(points,_,_) in repaired.items():
            for item in placed:
                if item.table.name not in (rel.child,rel.parent):
                    self.assertFalse(any(hits_rect(a,b,item.rect,12) for a,b in zip(points,points[1:])))

    def model(self):
        sql,_,_=d.collect_sql(Path(__file__).resolve().parents[2])
        return d.parse_ddl(sql)

    def test_contained_segment_and_touching_segment_are_collisions(self):
        rect=d.Rect(0,0,100,100)
        self.assertTrue(hits_rect((10,10),(20,20),rect))
        self.assertTrue(hits_rect((-10,0),(110,0),rect))
        self.assertFalse(hits_rect((-10,-1),(110,-1),rect))

    def test_router_bypasses_middle_card_and_keeps_fk_row_ports(self):
        parent=d.Table('parent',[d.Column('id','bigint',primary=True)])
        child=d.Table('child',[d.Column('id','bigint'),d.Column('parent_id','bigint',reference=('parent','id'))])
        blocker=d.Table('blocker',[d.Column('id','bigint')])
        positioned=[d.PositionedTable(child,d.Rect(0,0,160,120)),
                    d.PositionedTable(parent,d.Rect(600,0,160,120)),
                    d.PositionedTable(blocker,d.Rect(280,-40,240,240))]
        relations=d.relationships([child,parent,blocker])
        def factory(rel,points,cs,ps):
            return d.RelationshipRoute(rel,points[0],points[1],points[-2],points[-1],cs,ps,points)
        routes=route_all(positioned,relations,1,factory)
        self.assertEqual(routes,route_all(positioned,relations,1,factory))
        route=routes[0]
        self.assertEqual(73,route.start[1])
        self.assertEqual(47,route.end[1])
        self.assertFalse(d.route_crosses_rect(route,positioned[2].rect))
        self.assertGreater(len(route.waypoints),2)
        self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in d.route_segments(route)))
        for name,rect in port_aprons(positioned):
            if name=='blocker':
                self.assertFalse(any(hits_rect(a,b,rect) for a,b in d.route_segments(route)))

    def test_fixed_anchor_cannot_move(self):
        tables=self.model()
        initial=d.layout_tables(tables,options=LayoutOptions(steps=0,routing_passes=0))
        anchor=next(item for item in initial if item.table.name=='users')
        fixed={'users':(anchor.rect.x,anchor.rect.y)}
        changed=optimize_grid(initial,d.relationships(tables),LayoutOptions(steps=12),fixed)
        self.assertEqual(anchor.rect,next(i.rect for i in changed if i.table.name=='users'))
        self.assertFalse(any(d.overlaps(a.rect,b.rect) for i,a in enumerate(changed) for b in changed[i+1:]))

    def test_different_keys_get_separate_lanes_with_exact_ports(self):
        parent=d.Table('parent',[d.Column('first','bigint'),d.Column('second','bigint')])
        child=d.Table('child',[d.Column('first','bigint',reference=('parent','first')),
                               d.Column('second','bigint',reference=('parent','second'))])
        positioned=[d.PositionedTable(child,d.Rect(0,0,160,140)),
                    d.PositionedTable(parent,d.Rect(600,0,160,140))]
        relations=d.relationships([child,parent])
        paths={rel:(((160,y),(340,y),(340,220),(420,220),(420,y),(600,y)),1,-1)
               for rel,y in zip(relations,(47,73))}
        before=overlap_length(*(trim_ports(path[0]) for path in paths.values()))
        result=separate_lanes(positioned,paths)
        after=overlap_length(*(trim_ports(path[0]) for path in result.values()))
        self.assertGreater(before,250)
        self.assertEqual(0,after)
        self.assertEqual(result,separate_lanes(positioned,paths))
        for rel,(points,cs,ps) in result.items():
            self.assertEqual(paths[rel][0][0],points[0])
            self.assertEqual(paths[rel][0][-1],points[-1])
            self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(points,points[1:])))
            interior=trim_ports(points)
            self.assertFalse(any(hits_rect(a,b,item.rect,8) for a,b in zip(interior,interior[1:]) for item in positioned))

    def test_overlap_metric_counts_keys_sharing_a_table_but_excludes_terminal_stubs(self):
        first=((0,0),(100,0),(100,100))
        second=((0,0),(100,0),(100,-100))
        self.assertEqual(100,overlap_length(first,second))
        self.assertEqual(88,overlap_length(trim_ports(first),trim_ports(second)))
        self.assertEqual(0,overlap_length(((0,0),(100,0)),((100,0),(200,0))))
        self.assertEqual(0,overlap_length(((0,0),(100,0)),((50,-10),(50,10))))

    def test_terminal_fans_replace_staircases_keep_column_ports_and_clear_cards(self):
        child=d.Table('child',[d.Column('id','bigint')])
        parent=d.Table('parent',[d.Column('id','bigint')])
        blocker=d.Table('blocker',[d.Column('id','bigint')])
        positioned=[d.PositionedTable(child,d.Rect(0,0,160,140)),
                    d.PositionedTable(parent,d.Rect(-560,0,160,140)),
                    d.PositionedTable(blocker,d.Rect(-70,0,20,20))]
        points=((0,47),(-12,47),(-12,-13),(-90,-13),(-90,-100),(-300,-100),(-300,47),(-400,47))
        path,geometry=smooth_terminal_path(points,-1,1,positioned,'child','parent')
        # The obstructed end may retain its original route rather than force a steep fan.
        self.assertGreaterEqual(path.count('C '),1)
        self.assertEqual(points[0],geometry[0])
        self.assertEqual(points[-1],geometry[-1])
        self.assertEqual((path,geometry),smooth_terminal_path(points,-1,1,positioned,'child','parent'))
        self.assertTrue(any(a[0]!=b[0] and a[1]!=b[1] for a,b in zip(geometry,geometry[1:])))
        interior=trim_ports(geometry)
        self.assertFalse(any(hits_rect(a,b,item.rect,8 if item.table.name!='blocker' else 12)
                             for a,b in zip(interior,interior[1:]) for item in positioned))

    def test_real_schema_eliminates_card_hits_and_reduces_crossings_without_dropping_edges(self):
        tables=self.model()
        baseline=d.layout_tables(tables,options=LayoutOptions(steps=0,routing_passes=0))
        before=d.score_layout(baseline,d.legacy_relationship_routes(baseline))
        positioned=d.layout_tables(tables,options=LayoutOptions(steps=80,routing_passes=2))
        # Geometry regression checks use a short search budget. The complete default
        # layout is validated separately by the generator's snapshot/quality check.
        counts={}
        def bounded_repair(placed,paths):
            counts['before']=len(junction_conflicts(paths,merge_junctions(placed,paths)))
            return protect_merge_junctions(placed,paths,rounds=2)
        with patch('erd_optimizer.protect_merge_junctions',side_effect=bounded_repair):
            improved=d.relationship_routes(positioned,3)
        after=d.score_layout(positioned,improved)
        self.assertEqual(len(d.relationships(tables)),len(improved))
        self.assertEqual(0,after.table_intersections)
        if before.line_intersections:
            self.assertLess(after.line_intersections,before.line_intersections)
        else:
            self.assertEqual(0, after.line_intersections)
        self.assertLessEqual(len(junction_conflicts(
            {r.relationship:(r.waypoints,r.child_side,r.parent_side) for r in improved},improved[0].merge_zones)),counts.get('before', 0))

    def test_terminal_fan_cannot_join_a_returning_run_with_a_reverse_tangent(self):
        child=d.Table('child',[d.Column('id','bigint')])
        parent=d.Table('parent',[d.Column('id','bigint')])
        positioned=[d.PositionedTable(child,d.Rect(-160,0,160,140)),
                    d.PositionedTable(parent,d.Rect(600,-400,160,140))]
        points=((0,47),(12,47),(12,73),(200,73),(200,-80),(100,-80),(100,-353),(600,-353))
        for route,cs,ps,child_name,parent_name in ((points,1,-1,'child','parent'),
                                                  (tuple(reversed(points)),-1,1,'parent','child')):
            path,geometry=smooth_terminal_path(route,cs,ps,positioned,child_name,parent_name)
            self.assertIn('C ',path)
            self.assertEqual(route[0],geometry[0])
            self.assertEqual(route[-1],geometry[-1])
            for a,b,c in zip(geometry,geometry[1:],geometry[2:]):
                self.assertGreaterEqual((b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]),-1e-6)

    def test_shared_key_keeps_a_straight_common_entrance_and_rounds_remote_branches(self):
        child=d.Table('child',[d.Column('id','bigint')])
        parent=d.Table('parent',[d.Column('id','bigint')])
        positioned=[d.PositionedTable(child,d.Rect(0,0,160,140)),
                    d.PositionedTable(parent,d.Rect(600,0,160,140))]
        for x,y in ((340,-100),(352,260)):
            points=((160,47),(x,47),(x,y),(x+80,y),(x+80,47),(600,47))
            path,geometry=smooth_terminal_path(points,1,-1,positioned,'child','parent',True,True)
            self.assertIn('C ',path)
            self.assertEqual(points[0],geometry[0])
            self.assertEqual(points[-1],geometry[-1])
            self.assertTrue(all(p[1]==47 for p in geometry if p[0]<260 or p[0]>500))
            for a,b,c in zip(geometry,geometry[1:],geometry[2:]):
                self.assertGreaterEqual((b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]),-1e-6)

    def test_svg_contains_all_routed_points_and_connection_titles(self):
        tables=self.model()
        stats={}
        with patch('erd_optimizer.protect_merge_junctions',
                   side_effect=lambda placed,paths:protect_merge_junctions(placed,paths,rounds=2)):
            svg=d.render_svg(tables,options=LayoutOptions(steps=5,routing_passes=1),stats=stats)
        self.assertLessEqual(stats['unrelated_shared_length'],stats['shared_length'])
        self.assertLessEqual(stats['unrelated_overlapping_pairs'],stats['overlapping_pairs'])
        root=ET.fromstring(svg)
        x,y,w,h=map(float,root.attrib['viewBox'].split())
        paths=[p for p in root.findall('{http://www.w3.org/2000/svg}path') if p.get('class')=='relationship']
        self.assertEqual(len(d.relationships(tables)),len(paths))
        for path in paths:
            self.assertIsNotNone(path.find('{http://www.w3.org/2000/svg}title'))
            values=list(map(float,re.findall(r'-?\d+(?:\.\d+)?(?:e[+-]?\d+)?',path.attrib['d'])))
            for px,py in zip(values[::2],values[1::2]):
                self.assertTrue(x<=px<=x+w)
                self.assertTrue(y<=py<=y+h)

    def test_config_and_cli_overrides_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            file=root / d.LAYOUT_YAML
            file.parent.mkdir(parents=True)
            file.write_text('optimization:\n  steps: 75\n  routing_passes: 2\n  seed: 7\n',encoding='utf-8')
            self.assertEqual(LayoutOptions(75,2,7),d.load_layout_options(root))
            self.assertEqual(LayoutOptions(0,1,7),d.load_layout_options(root,steps=0,routing_passes=1))
        for kwargs in ({'steps':-1},{'steps':True},{'routing_passes':11},{'seed':'random'}):
            with self.assertRaises(ValueError): LayoutOptions(**kwargs)


if __name__=='__main__':
    unittest.main()
