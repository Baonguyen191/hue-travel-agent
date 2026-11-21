import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ComingSoonPage } from "./pages/ComingSoonPage";
import { ExplorePage } from "./pages/ExplorePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlaceDetailPage } from "./pages/PlaceDetailPage";
import { PlanStubPage } from "./pages/PlanStubPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ComingSoonPage title="Nhập yêu cầu" />} />
        <Route path="explore" element={<ExplorePage />} />
        <Route path="explore/:poiId" element={<PlaceDetailPage />} />
        <Route path="plan/:threadId" element={<PlanStubPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
