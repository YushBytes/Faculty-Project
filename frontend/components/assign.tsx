"use client";

/** Staff assignment drawers: teaching (offering faculty) and course coordination. The server
 * decides who may do this; the drawer only offers it where the workspace says it can. */
import { useState } from "react";
import { UserMinus, UserPlus } from "lucide-react";
import { offeringsApi, orgApi, usersApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/http";
import { useSession } from "@/lib/auth/session";
import { useApi } from "@/lib/hooks/use-api";
import { Badge, Drawer, Empty, LoadingBlock } from "@/components/ui";
import { ROLE_SHORT } from "@/lib/format";

export function FacultyDrawer({ offeringId, label, departmentId, onClose, onChanged }: { offeringId: string; label: string; departmentId?: string | null; onClose: () => void; onChanged: () => void }) {
  const { notify } = useSession();
  const [search, setSearch] = useState("");
  const offering = useApi(() => offeringsApi.get(offeringId), [offeringId]);
  const staff = useApi(() => usersApi.list({ department_id: departmentId ?? undefined, is_active: true, q: search || undefined, limit: 50 }), [departmentId, search]);
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (userId: string, add: boolean) => {
    setBusy(userId);
    try {
      if (add) await offeringsApi.assignFaculty(offeringId, userId);
      else await offeringsApi.unassignFaculty(offeringId, userId);
      notify(add ? "Faculty assigned" : "Faculty removed", `${label} · recorded in the audit log`);
      offering.reload();
      onChanged();
    } catch (err) {
      notify("Not changed", err instanceof ApiError ? err.message : String(err), "error");
    } finally {
      setBusy(null);
    }
  };
  const assigned = new Set(offering.data?.faculty.map((f) => f.id));
  return (
    <Drawer title="Teaching assignment" subtitle={label} onClose={onClose}>
      <div>
        <div className="label" style={{ marginBottom: 8 }}>Currently teaching</div>
        {offering.loading ? <LoadingBlock rows={2} /> : offering.data?.faculty.length ? (
          <div className="list">{offering.data.faculty.map((f) => (
            <div className="list-item" key={f.id}><div className="grow"><b>{f.full_name}</b><small>{f.email}</small></div>
              <button className="btn btn-sm btn-danger" disabled={busy === f.id} onClick={() => act(f.id, false)}><UserMinus size={15} /> Remove</button></div>))}
          </div>
        ) : <Empty title="Nobody assigned" />}
      </div>
      <div>
        <div className="label" style={{ marginBottom: 8 }}>Assign someone</div>
        <input className="input" placeholder="Search by name, email or staff id" value={search} onChange={(e) => setSearch(e.target.value)} />
        <div className="list" style={{ marginTop: 8 }}>
          {staff.loading ? <LoadingBlock rows={4} /> : staff.data?.items.filter((u) => u.role !== "ADMIN").map((u) => (
            <div className="list-item" key={u.id}>
              <div className="grow"><b>{u.full_name}</b><small>{u.email}{u.employee_code ? ` · ${u.employee_code}` : ""}</small></div>
              <Badge>{ROLE_SHORT[u.role]}</Badge>
              <button className="btn btn-sm" disabled={assigned.has(u.id) || busy === u.id} onClick={() => act(u.id, true)}><UserPlus size={15} /> {assigned.has(u.id) ? "Assigned" : "Assign"}</button>
            </div>
          ))}
        </div>
      </div>
    </Drawer>
  );
}

export function CoordinatorDrawer({ courseId, onClose, onChanged }: { courseId: string; onClose: () => void; onChanged: () => void }) {
  const { notify } = useSession();
  const course = useApi(() => orgApi.course(courseId), [courseId]);
  const candidates = useApi(
    () => usersApi.list({ role: "COURSE_COORDINATOR", department_id: course.data?.department.id, is_active: true, limit: 100 }),
    [course.data?.department.id],
    !!course.data,
  );
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (userId: string, add: boolean) => {
    setBusy(userId);
    try {
      if (add) await orgApi.addCoordinator(courseId, userId);
      else await orgApi.removeCoordinator(courseId, userId);
      notify(add ? "Coordinator assigned" : "Coordinator removed", course.data?.code);
      course.reload();
      onChanged();
    } catch (err) {
      notify("Not changed", err instanceof ApiError ? err.message : String(err), "error");
    } finally {
      setBusy(null);
    }
  };
  const current = new Set(course.data?.coordinators.map((c) => c.id));
  return (
    <Drawer title="Course coordinators" subtitle={course.data ? `${course.data.code} ${course.data.name}` : ""} onClose={onClose}>
      {course.loading ? <LoadingBlock /> : (
        <>
          <div className="list">{course.data?.coordinators.map((c) => (
            <div className="list-item" key={c.id}><div className="grow"><b>{c.full_name}</b><small>{c.email}</small></div><button className="btn btn-sm btn-danger" disabled={busy === c.id} onClick={() => act(c.id, false)}>Remove</button></div>
          ))}{!course.data?.coordinators.length && <Empty title="No coordinator yet" />}</div>
          <div className="label">Course Coordinators in the department</div>
          <div className="list">{candidates.data?.items.map((u) => (
            <div className="list-item" key={u.id}><div className="grow"><b>{u.full_name}</b><small>{u.email}</small></div><button className="btn btn-sm" disabled={current.has(u.id) || busy === u.id} onClick={() => act(u.id, true)}>{current.has(u.id) ? "Coordinating" : "Assign"}</button></div>
          ))}</div>
          <p className="muted" style={{ fontSize: 13.5 }}>To appoint someone new, give them the Course Coordinator role under People first. Changing coordinators never changes any marks or results.</p>
        </>
      )}
    </Drawer>
  );
}
