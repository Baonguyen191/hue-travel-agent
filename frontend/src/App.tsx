import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { BookingTab } from "./pages/BookingTab";
import { BudgetTab } from "./pages/BudgetTab";
import { ChatPage } from "./pages/ChatPage";
import { ExplorePage } from "./pages/ExplorePage";
import { ItineraryTab } from "./pages/ItineraryTab";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlaceDetailPage } from "./pages/PlaceDetailPage";
import { PlanLayout } from "./pages/PlanLayout";
import { RequestPage } from "./pages/RequestPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ChatPage />} />
        <Route path="form" element={<RequestPage />} />
        <Route path="explore" element={<ExplorePage />} />
        <Route path="explore/:poiId" element={<PlaceDetailPage />} />
        <Route path="plan/:threadId" element={<PlanLayout />}>
          <Route index element={<ItineraryTab />} />
          <Route path="budget" element={<BudgetTab />} />
          <Route path="booking" element={<BookingTab />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
