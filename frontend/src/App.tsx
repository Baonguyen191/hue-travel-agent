import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ComingSoonPage } from "./pages/ComingSoonPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlanStubPage } from "./pages/PlanStubPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ComingSoonPage title="Nhập yêu cầu" />} />
        <Route path="explore" element={<ComingSoonPage title="Khám phá Huế" />} />
        <Route path="explore/:poiId" element={<ComingSoonPage title="Chi tiết địa điểm" />} />
        <Route path="plan/:threadId" element={<PlanStubPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
